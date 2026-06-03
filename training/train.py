"""
training/train.py
=================
LoRA SFT fine-tuning of Gemma 4 E2B on synthetic computer-use data.

This script runs INSIDE the AzureML training job on the A100 node.
It is NOT executed from the laptop. The control-plane code in
src/03_submit_training_job.py packages this file + conda.yml and submits it.

Pipeline:
1. Load Gemma 4 (bf16) and its tokenizer from the AzureML catalog model mount
    by default. HF token is only needed for the optional Hugging Face fallback.
2. Load the train + validation JSONL from the mounted Data asset.
3. Configure LoRA adapters on attention + MLP projection layers.
4. Use TRL's SFTTrainer to fine-tune. SFTTrainer auto-detects the messages
   format and applies the tokenizer's chat template per record.
5. Save the LoRA adapter and a merged full model to the AzureML outputs
    directory so deployment does not need to remount the adapter later.

Memory budget (A100 80GB, bf16):
- Base model weights:        ~8 GB
- LoRA trainable params:     ~80 MB
- Optimizer state (LoRA):    ~160 MB
- Activations (gradckpt on): ~10-20 GB at seq_len=2048, batch=4
- Total:                     ~30-40 GB → fits comfortably
"""
from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import sys
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
)
from trl import SFTConfig, SFTTrainer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gemma4-lora-sft")
GEMMA_MODEL_ID = "google/gemma-4-e2b-it"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LoRA SFT of Gemma 4 E4B on synthetic data")
    p.add_argument("--model_id", default=GEMMA_MODEL_ID)
    p.add_argument("--base_model_name", default=GEMMA_MODEL_ID)
    p.add_argument("--base_model_asset_id", default="")
    p.add_argument("--train_file", required=True, help="Path (in mounted data asset) to train JSONL")
    p.add_argument("--val_file", required=True, help="Path (in mounted data asset) to val JSONL")
    p.add_argument("--output_dir", default="./outputs", help="AzureML outputs dir — adapter saved here")
    p.add_argument("--num_epochs", type=int, default=3)
    p.add_argument("--per_device_batch_size", type=int, default=4)
    p.add_argument("--grad_accum_steps", type=int, default=4)
    p.add_argument("--learning_rate", type=float, default=2e-4)
    p.add_argument("--max_seq_length", type=int, default=2048)
    p.add_argument("--lora_rank", type=int, default=16)
    p.add_argument("--lora_alpha", type=int, default=32)
    p.add_argument("--lora_dropout", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def load_jsonl_as_dataset(path: str) -> Dataset:
    """Read JSONL of {"messages": [...]} into an HF Dataset."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    log.info(f"  loaded {len(records)} records from {path}")
    return Dataset.from_list(records)


def load_tokenizer(model_id: str, token_kwargs: dict) -> AutoTokenizer:
    tokenizer_kwargs = {
        "trust_remote_code": True,
        "extra_special_tokens": {},
        **token_kwargs,
    }
    try:
        return AutoTokenizer.from_pretrained(model_id, **tokenizer_kwargs)
    except AttributeError as exc:
        if "'list' object has no attribute 'keys'" not in str(exc):
            raise
        log.warning("Fast tokenizer rejected catalog extra_special_tokens metadata; retrying with use_fast=False")
        return AutoTokenizer.from_pretrained(model_id, use_fast=False, **tokenizer_kwargs)


def main() -> None:
    args = parse_args()
    model_path = Path(args.model_id)
    model_is_local = model_path.exists()

    log.info("=" * 60)
    log.info("Gemma 4 E2B LoRA SFT - training job start")
    log.info("=" * 60)
    log.info(f"  model_id:        {args.model_id}")
    log.info(f"  base_model_name: {args.base_model_name}")
    log.info(f"  base_asset_id:   {args.base_model_asset_id or 'none'}")
    log.info(f"  train_file:      {args.train_file}")
    log.info(f"  val_file:        {args.val_file}")
    log.info(f"  output_dir:      {args.output_dir}")
    log.info(f"  num_epochs:      {args.num_epochs}")
    log.info(f"  batch_size:      {args.per_device_batch_size} x grad_accum={args.grad_accum_steps}")
    log.info(f"  learning_rate:   {args.learning_rate}")
    log.info(f"  lora_rank/alpha: {args.lora_rank}/{args.lora_alpha}")
    log.info(f"  CUDA available:  {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        log.info(f"  GPU:             {torch.cuda.get_device_name(0)}")
        log.info(f"  GPU memory:      {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    # Hugging Face token - only required when loading from Hugging Face directly.
    hf_token = os.environ.get("HF_TOKEN")
    if not model_is_local and not hf_token:
        log.error("HF_TOKEN env var not set and model_id is not a local AzureML catalog mount.")
        sys.exit(1)
    token_kwargs = {"token": hf_token} if hf_token else {}

    # --- 1. Tokenizer + base model ----------------------------------------
    log.info("Loading tokenizer...")
    tokenizer = load_tokenizer(args.model_id, token_kwargs)
    # Gemma uses a chat template; ensure pad token is set for training
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    log.info("Loading base model in bf16...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        trust_remote_code=True,
        **token_kwargs,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",  # scaled dot-product attention; flash_attention_2 also works
    )
    # Enable gradient checkpointing — required to fit reasonable batch sizes
    model.gradient_checkpointing_enable()
    model.config.use_cache = False  # incompatible with gradient checkpointing during training

    # --- 2. LoRA config ---------------------------------------------------
    # Gemma4 wraps projection layers in Gemma4ClippableLinear; PEFT can inject
    # LoRA into the inner torch.nn.Linear child, not the wrapper itself.
    base_lora_targets = [
        "q_proj", "k_proj", "v_proj", "o_proj",       # attention
        "gate_proj", "up_proj", "down_proj",          # MLP
    ]
    module_names = {name for name, _ in model.named_modules()}
    target_modules = []
    for target in base_lora_targets:
        wrapped_target = f"{target}.linear"
        if any(name.endswith(wrapped_target) for name in module_names):
            target_modules.append(wrapped_target)
        else:
            target_modules.append(target)
    log.info("  LoRA target modules: %s", ", ".join(target_modules))

    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    )
    model = get_peft_model(model, lora_config)
    trainable, total = 0, 0
    for _, param in model.named_parameters():
        total += param.numel()
        if param.requires_grad:
            trainable += param.numel()
    log.info(f"  trainable params: {trainable:,} / {total:,} ({100*trainable/total:.3f}%)")

    # --- 3. Data ---------------------------------------------------------
    log.info("Loading datasets...")
    train_ds = load_jsonl_as_dataset(args.train_file)
    val_ds = load_jsonl_as_dataset(args.val_file)

    # --- 4. Trainer ------------------------------------------------------
    # SFTConfig is a TrainingArguments subclass with SFT-specific knobs.
    # When the dataset has a "messages" column, SFTTrainer auto-applies
    # tokenizer.apply_chat_template per record — no custom formatter needed.
    sft_config = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.num_epochs,
        per_device_train_batch_size=args.per_device_batch_size,
        per_device_eval_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.grad_accum_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        max_seq_length=args.max_seq_length,
        bf16=True,
        tf32=True,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,         # keep last 2 checkpoints, save disk
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to=[],               # avoid legacy azureml-sdk callback dependency
        seed=args.seed,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        # Pack short examples together for throughput; safe for instruction data
        packing=False,
        dataset_kwargs={"add_special_tokens": False},  # chat template adds them
    )

    log.info("Building SFTTrainer...")
    trainer_kwargs = {
        "model": model,
        "args": sft_config,
        "train_dataset": train_ds,
        "eval_dataset": val_ds,
    }
    if "processing_class" in inspect.signature(SFTTrainer.__init__).parameters:
        trainer_kwargs["processing_class"] = tokenizer
    else:
        trainer_kwargs["tokenizer"] = tokenizer
    trainer = SFTTrainer(**trainer_kwargs)

    log.info("Starting training...")
    train_result = trainer.train()
    log.info(f"Training done. Final train loss: {train_result.training_loss:.4f}")

    log.info("Running final eval...")
    eval_result = trainer.evaluate()
    log.info(f"Eval loss: {eval_result['eval_loss']:.4f}")

    # --- 5. Save adapter -------------------------------------------------
    adapter_dir = Path(args.output_dir) / "lora_adapter"
    log.info(f"Saving LoRA adapter to {adapter_dir}")
    trainer.model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)

    # Write a small metadata file the deploy step uses
    metadata = {
        "base_model": args.base_model_name,
        "base_model_asset_id": args.base_model_asset_id,
        "base_model_loaded_from": "azureml_catalog_mount" if model_is_local else "huggingface",
        "adapter_type": "lora",
        "lora_rank": args.lora_rank,
        "lora_alpha": args.lora_alpha,
        "final_train_loss": train_result.training_loss,
        "final_eval_loss": eval_result["eval_loss"],
        "num_train_records": len(train_ds),
        "num_val_records": len(val_ds),
        "trainable_params": trainable,
        "total_params": total,
    }
    (adapter_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    # --- 6. Save merged model -------------------------------------------
    merged_dir = Path(args.output_dir) / "merged_model"
    log.info(f"Merging LoRA adapter into base model and saving to {merged_dir}")
    merged_model = trainer.model.merge_and_unload()
    merged_model.config.use_cache = True
    merged_model.save_pretrained(merged_dir, safe_serialization=True, max_shard_size="2GB")
    tokenizer.save_pretrained(merged_dir)
    (merged_dir / "metadata.json").write_text(json.dumps({**metadata, "model_type": "merged_lora"}, indent=2))

    log.info("=" * 60)
    log.info("Job complete. Adapter artifacts in ./outputs/lora_adapter/ and merged model in ./outputs/merged_model/")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
