# Streamlit Demo App

Run this from the `poc-2-gemma4-finetune` folder:

```powershell
streamlit run demo_app/app.py
```

The app uses one AzureML managed online endpoint on `Standard_NC24ads_A100_v4`.
The endpoint loads base `google/gemma-4-E4B-it` plus the LoRA adapter once, then
each request sets `use_adapter=false` for the left/base response or
`use_adapter=true` for the right/fine-tuned response.

Use the sidebar button to create/update the endpoint before the customer demo.
Use the delete button immediately after the demo to stop A100 hourly billing.