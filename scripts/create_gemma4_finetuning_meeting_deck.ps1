param(
    [string]$OutputPath = "",
    [string]$ExportDir = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $Root "demo\molina-gemma4-finetuning-meeting-deck.pptx"
}
if ([string]::IsNullOrWhiteSpace($ExportDir)) {
    $ExportDir = Join-Path $Root "demo\molina-gemma4-finetuning-meeting-deck-images"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
New-Item -ItemType Directory -Force -Path $ExportDir | Out-Null

function Inch([double]$Value) { return [single]($Value * 72.0) }

function OleColor([string]$Hex) {
    $clean = $Hex.TrimStart("#")
    $r = [Convert]::ToInt32($clean.Substring(0, 2), 16)
    $g = [Convert]::ToInt32($clean.Substring(2, 2), 16)
    $b = [Convert]::ToInt32($clean.Substring(4, 2), 16)
    return [int]($r + ($g * 256) + ($b * 65536))
}

$Theme = @{
    Ink = "201F1E"
    Muted = "605E5C"
    SoftText = "8A8886"
    White = "FFFFFF"
    Canvas = "F7F9FC"
    Panel = "FFFFFF"
    Border = "D2D0CE"
    Blue = "0078D4"
    BlueDark = "004578"
    BlueLight = "D7EBFF"
    Teal = "00B7C3"
    TealDark = "038387"
    Green = "107C10"
    GreenLight = "DFF6DD"
    Orange = "FF8C00"
    OrangeLight = "FFF4CE"
    Red = "D13438"
    RedLight = "FDE7E9"
    Purple = "5C2D91"
    PurpleLight = "EDE7F6"
    Graphite = "252423"
}

$SlideW = 13.333
$SlideH = 7.5
$msoTextOrientationHorizontal = 1
$ppLayoutBlank = 12
$msoShapeRectangle = 1
$msoShapeRoundedRectangle = 5
$msoShapeOval = 9
$msoShapeRightArrow = 33
$msoShapeHexagon = 10
$msoLineSolid = 1
$msoTrue = -1
$msoFalse = 0

function Add-Box {
    param(
        $Slide,
        [double]$X,
        [double]$Y,
        [double]$W,
        [double]$H,
        [string]$Fill = "FFFFFF",
        [string]$Line = "FFFFFF",
        [double]$LineWeight = 0.5,
        [switch]$Rounded,
        [double]$Transparency = 0.0
    )
    $shapeType = if ($Rounded) { $msoShapeRoundedRectangle } else { $msoShapeRectangle }
    $shape = $Slide.Shapes.AddShape($shapeType, (Inch $X), (Inch $Y), (Inch $W), (Inch $H))
    $shape.Fill.Visible = $msoTrue
    $shape.Fill.ForeColor.RGB = OleColor $Fill
    if ($Transparency -gt 0) { $shape.Fill.Transparency = $Transparency }
    if ($Line -eq "none") {
        $shape.Line.Visible = $msoFalse
    } else {
        $shape.Line.Visible = $msoTrue
        $shape.Line.ForeColor.RGB = OleColor $Line
        $shape.Line.Weight = $LineWeight
    }
    return $shape
}

function Add-Circle {
    param($Slide, [double]$X, [double]$Y, [double]$D, [string]$Fill, [string]$Line = "none", [double]$Transparency = 0.0)
    $shape = $Slide.Shapes.AddShape($msoShapeOval, (Inch $X), (Inch $Y), (Inch $D), (Inch $D))
    $shape.Fill.ForeColor.RGB = OleColor $Fill
    if ($Transparency -gt 0) { $shape.Fill.Transparency = $Transparency }
    if ($Line -eq "none") { $shape.Line.Visible = $msoFalse } else { $shape.Line.ForeColor.RGB = OleColor $Line }
    return $shape
}

function Add-Line {
    param($Slide, [double]$X1, [double]$Y1, [double]$X2, [double]$Y2, [string]$Color = "0078D4", [double]$Weight = 2.0)
    $shape = $Slide.Shapes.AddLine((Inch $X1), (Inch $Y1), (Inch $X2), (Inch $Y2))
    $shape.Line.ForeColor.RGB = OleColor $Color
    $shape.Line.Weight = $Weight
    return $shape
}

function Add-Text {
    param(
        $Slide,
        [string]$Text,
        [double]$X,
        [double]$Y,
        [double]$W,
        [double]$H,
        [double]$Size = 18,
        [string]$Color = "201F1E",
        [switch]$Bold,
        [string]$Align = "Left",
        [string]$Font = "Aptos",
        [double]$Margin = 0.04
    )
    $box = $Slide.Shapes.AddTextbox($msoTextOrientationHorizontal, (Inch $X), (Inch $Y), (Inch $W), (Inch $H))
    $box.TextFrame2.MarginLeft = (Inch $Margin)
    $box.TextFrame2.MarginRight = (Inch $Margin)
    $box.TextFrame2.MarginTop = (Inch 0.02)
    $box.TextFrame2.MarginBottom = (Inch 0.02)
    $box.TextFrame2.WordWrap = $msoTrue
    $range = $box.TextFrame2.TextRange
    $range.Text = ($Text -replace "\\n", [Environment]::NewLine)
    $range.Font.Name = $Font
    $range.Font.Size = $Size
    $range.Font.Fill.ForeColor.RGB = OleColor $Color
    $range.Font.Bold = if ($Bold) { $msoTrue } else { $msoFalse }
    $alignment = switch ($Align) {
        "Center" { 2 }
        "Right" { 3 }
        default { 1 }
    }
    $range.ParagraphFormat.Alignment = $alignment
    return $box
}

function Add-Title {
    param($Slide, [string]$Title, [string]$Kicker = "Molina EIM | Gemma 4B-class SLM fine-tuning demo")
    Add-Text $Slide $Kicker 0.55 0.25 7.0 0.28 9.5 $Theme.Blue -Bold -Font "Segoe UI" | Out-Null
    Add-Text $Slide $Title 0.55 0.55 8.8 0.72 29 $Theme.Ink -Bold -Font "Aptos Display" | Out-Null
    Add-Text $Slide "Microsoft AI + AzureML" 10.55 0.28 2.25 0.25 8.5 $Theme.Muted -Align "Right" -Font "Segoe UI" | Out-Null
}

function Add-Footer {
    param($Slide, [int]$Index)
    Add-Text $Slide ("Molina Healthcare EIM demo | {0:00}" -f $Index) 10.15 7.12 2.65 0.2 7.5 $Theme.SoftText -Align "Right" -Font "Segoe UI" | Out-Null
}

function Add-Notes {
    param($Slide, [string]$Notes)
    try {
        $Slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = $Notes
    } catch {
        $noteBox = $Slide.NotesPage.Shapes.AddTextbox($msoTextOrientationHorizontal, 40, 360, 620, 220)
        $noteBox.TextFrame.TextRange.Text = $Notes
    }
}

function New-TalkTrack {
    param([string[]]$Lines)
    return ($Lines -join [Environment]::NewLine)
}

function New-Slide {
    param($Presentation, [int]$Index, [string]$Background = "F7F9FC")
    $slide = $Presentation.Slides.Add($Index, $ppLayoutBlank)
    Add-Box $slide 0 0 $SlideW $SlideH $Background "none" | Out-Null
    return $slide
}

function Add-Chip {
    param($Slide, [string]$Text, [double]$X, [double]$Y, [double]$W, [string]$Fill, [string]$Color = "FFFFFF")
    Add-Box $Slide $X $Y $W 0.34 $Fill "none" -Rounded | Out-Null
    Add-Text $Slide $Text ($X + 0.1) ($Y + 0.065) ($W - 0.2) 0.16 8.5 $Color -Bold -Align "Center" -Font "Segoe UI" | Out-Null
}

function Add-Callout {
    param($Slide, [string]$Label, [string]$Value, [double]$X, [double]$Y, [double]$W, [string]$Accent)
    Add-Box $Slide $X $Y $W 1.05 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $Slide $Value ($X + 0.18) ($Y + 0.14) ($W - 0.36) 0.38 25 $Accent -Bold -Font "Aptos Display" | Out-Null
    Add-Text $Slide $Label ($X + 0.18) ($Y + 0.62) ($W - 0.36) 0.24 9.5 $Theme.Muted -Font "Segoe UI" | Out-Null
}

function Add-Step {
    param($Slide, [int]$Number, [string]$Title, [string]$Body, [double]$X, [double]$Y, [double]$W, [string]$Color)
    Add-Box $Slide $X $Y $W 1.05 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Circle $Slide ($X + 0.16) ($Y + 0.18) 0.46 $Color | Out-Null
    Add-Text $Slide ([string]$Number) ($X + 0.17) ($Y + 0.25) 0.43 0.18 11 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $Slide $Title ($X + 0.75) ($Y + 0.16) ($W - 0.95) 0.22 11.5 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $Slide $Body ($X + 0.75) ($Y + 0.47) ($W - 0.95) 0.42 8.5 $Theme.Muted -Font "Segoe UI" | Out-Null
}

function Add-ScoreCell {
    param($Slide, [string]$Text, [bool]$Pass, [double]$X, [double]$Y, [double]$W)
    $fill = if ($Pass) { $Theme.GreenLight } else { $Theme.RedLight }
    $color = if ($Pass) { $Theme.Green } else { $Theme.Red }
    Add-Box $Slide $X $Y $W 0.36 $fill "none" -Rounded | Out-Null
    Add-Text $Slide $Text ($X + 0.04) ($Y + 0.075) ($W - 0.08) 0.14 8.5 $color -Bold -Align "Center" -Font "Segoe UI" | Out-Null
}

function Add-Slide1 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index $Theme.Graphite
    Add-Circle $slide 9.35 -1.1 4.1 $Theme.Blue  "none" 0.15 | Out-Null
    Add-Circle $slide 10.85 4.45 2.6 $Theme.Teal "none" 0.30 | Out-Null
    Add-Text $slide "Molina EIM" 0.65 0.55 2.2 0.28 10 $Theme.Teal -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Gemma 4B-class fine-tuning for a browser-action agent" 0.65 1.15 7.5 1.2 34 $Theme.White -Bold -Font "Aptos Display" | Out-Null
    Add-Text $slide "A customer-ready walkthrough: problem framing, base-model gap, LoRA fine-tuning, synthetic data, AzureML resources, and the before/after demo result." 0.68 2.62 6.6 0.72 15 $Theme.BlueLight -Font "Aptos" | Out-Null
    Add-Chip $slide "AzureML managed compute" 0.68 3.7 2.1 $Theme.Blue | Out-Null
    Add-Chip $slide "Synthetic data only" 2.95 3.7 1.75 $Theme.TealDark | Out-Null
    Add-Chip $slide "LoRA adapter" 4.86 3.7 1.35 $Theme.Green | Out-Null
    Add-Box $slide 8.1 1.38 3.9 3.75 "11100F" "605E5C" -Rounded | Out-Null
    Add-Box $slide 8.45 1.78 3.2 0.42 $Theme.BlueDark "none" -Rounded | Out-Null
    Add-Text $slide "Browser Agent" 8.64 1.87 2.7 0.12 9.2 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 8.45 2.45 1.35 0.52 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "DOM" 8.8 2.62 0.65 0.12 9 $Theme.BlueDark -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 10.05 2.45 1.35 0.52 $Theme.PurpleLight "none" -Rounded | Out-Null
    Add-Text $slide "Intent" 10.35 2.62 0.75 0.12 9 $Theme.Purple -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Line $slide 9.82 2.7 10.03 2.7 $Theme.SoftText 1.6 | Out-Null
    Add-Box $slide 9.05 3.55 1.78 0.64 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "JSON actions" 9.24 3.78 1.4 0.12 9 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Line $slide 9.12 3.02 9.63 3.52 $Theme.Teal 2.2 | Out-Null
    Add-Line $slide 10.73 3.02 10.2 3.52 $Theme.Teal 2.2 | Out-Null
    Add-Text $slide "Prepared for Chirag, Dhanshri, and EIM team" 0.68 6.72 5.3 0.22 9.5 "C8C6C4" -Font "Segoe UI" | Out-Null
    Add-Notes $slide "Last call, Chirag asked whether we could use a small open model for a browsing or computer-use style agent, and whether we could fine-tune it using the A100 capacity already available. This deck is the meeting narrative for that answer. I am going to show the problem, what base Gemma can and cannot do natively, why fine-tuning is the right lever for this behavior, exactly what we trained, the AzureML and Foundry-adjacent resources we used, and how the fine-tuned model changes the result."
    return $slide
}

function Add-Slide2 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "The problem: browsing agents need repeatable actions"
    Add-Text $slide "Chirag's ask maps to a browser-control agent: read a page state, understand the user's intent, and return a precise machine-executable action plan." 0.65 1.35 6.2 0.55 14 $Theme.Muted -Font "Aptos" | Out-Null
    $y = 2.2
    Add-Box $slide 0.75 $y 2.55 2.5 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "1" 1.0 ($y + 0.26) 0.28 0.2 13 $Theme.Blue -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "User goal" 1.35 ($y + 0.22) 1.5 0.2 14 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Open a prior authorization, run policy check, submit in the right order." 1.0 ($y + 0.83) 1.95 0.9 16 $Theme.BlueDark -Bold -Font "Aptos" | Out-Null
    Add-Box $slide 4.0 $y 2.55 2.5 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "2" 4.25 ($y + 0.26) 0.28 0.2 13 $Theme.TealDark -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Page state" 4.6 ($y + 0.22) 1.5 0.2 14 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "DOM snippet with noisy IDs plus stable data-eim attributes." 4.3 ($y + 0.84) 1.9 0.8 15 $Theme.TealDark -Bold -Font "Aptos" | Out-Null
    Add-Box $slide 7.25 $y 2.55 2.5 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "3" 7.5 ($y + 0.26) 0.28 0.2 13 $Theme.Green -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Action contract" 7.85 ($y + 0.22) 1.7 0.2 14 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Return only JSON: click, type, extract - no prose, no markdown." 7.55 ($y + 0.83) 1.95 0.85 15 $Theme.Green -Bold -Font "Aptos" | Out-Null
    Add-Box $slide 10.5 $y 2.05 2.5 $Theme.Graphite "none" -Rounded | Out-Null
    Add-Text $slide "Why it matters" 10.75 ($y + 0.28) 1.55 0.22 13 $Theme.White -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Repeatable\nAuditable\nLow variance\nWorkflow-safe" 10.82 ($y + 0.83) 1.35 1.1 15 $Theme.BlueLight -Bold -Align "Center" -Font "Aptos" | Out-Null
    Add-Line $slide 3.32 3.45 3.95 3.45 $Theme.Blue 2.5 | Out-Null
    Add-Line $slide 6.57 3.45 7.20 3.45 $Theme.Teal 2.5 | Out-Null
    Add-Line $slide 9.82 3.45 10.45 3.45 $Theme.Green 2.5 | Out-Null
    Add-Callout $slide "Output is executable, not just plausible" "JSON" 0.75 5.42 2.4 $Theme.Blue
    Add-Callout $slide "Stable selectors survive UI-generated IDs" "data-eim" 3.55 5.42 2.4 $Theme.TealDark
    Add-Callout $slide "Healthcare-safe demo data" "0 PHI" 6.35 5.42 2.4 $Theme.Green
    Add-Callout $slide "One narrow workflow first" "Pilot" 9.15 5.42 2.4 $Theme.Purple
    Add-Footer $slide $Index
    Add-Notes $slide "The business problem is not simply that we need a model to answer questions. A browsing agent has to turn a human instruction into a deterministic sequence of actions. It needs to know which workspace to open, which field to type into, which button to press, and which value to extract. If it returns a nice paragraph, that is not useful to an automation layer. The demo focuses on the parts that matter for this ask: a compact DOM, a user instruction, and a strict JSON action plan with stable selectors."
    return $slide
}

function Add-Slide3 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "What this demo considers - and why"
    Add-Text $slide "The goal is a disciplined answer to a narrow question: can a small SLM learn Molina/EIM browser-action behavior well enough to justify a pilot?" 0.65 1.32 8.9 0.45 13.5 $Theme.Muted -Font "Aptos" | Out-Null
    $cards = @(
        @{T="Workflow contract"; B="DOM + instruction in, JSON action plan out. This is the core browser-agent interface."; C=$Theme.Blue},
        @{T="Small model baseline"; B="Gemma 4B-class SLM can often parse the task, but generic behavior is inconsistent."; C=$Theme.Purple},
        @{T="Synthetic training data"; B="Healthcare-shaped, deterministic, fake members and claims. No Molina PHI."; C=$Theme.Green},
        @{T="Objective checks"; B="Valid JSON, action schema, stable selectors, workflow navigation, required actions, order."; C=$Theme.Orange},
        @{T="Azure execution path"; B="A100 managed compute, AzureML job lineage, model registration, online endpoint."; C=$Theme.TealDark},
        @{T="Cost and cleanup"; B="LoRA keeps training small; endpoint is deleted after demo to stop A100 billing."; C=$Theme.Red}
    )
    for ($i = 0; $i -lt $cards.Count; $i++) {
        $row = [math]::Floor($i / 3)
        $col = $i % 3
        $x = 0.75 + ($col * 4.1)
        $y = 2.05 + ($row * 2.0)
        Add-Box $slide $x $y 3.55 1.48 $Theme.Panel $Theme.Border -Rounded | Out-Null
        Add-Circle $slide ($x + 0.2) ($y + 0.24) 0.42 $cards[$i].C | Out-Null
        Add-Text $slide ([string]($i + 1)) ($x + 0.21) ($y + 0.31) 0.4 0.12 10 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
        Add-Text $slide $cards[$i].T ($x + 0.78) ($y + 0.22) 2.45 0.22 13 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
        Add-Text $slide $cards[$i].B ($x + 0.78) ($y + 0.55) 2.48 0.65 8.8 $Theme.Muted -Font "Segoe UI" | Out-Null
    }
    Add-Footer $slide $Index
    Add-Notes $slide "This slide is the scoping slide. I would make clear that we are not claiming to have built a universal healthcare assistant. We are testing the behavior Chirag asked about: can a small model be taught to operate in a browser-like workflow with a strict output contract? That is why the demo includes a baseline, synthetic but realistic page states, explicit pass-fail checks, AzureML job lineage, and cost controls."
    return $slide
}

function Add-Slide4 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Base Gemma misses the EIM contract"
    Add-Text $slide "In the live demo, the base model often gets surface structure right, but misses the stable EIM automation contract." 0.65 1.3 7.0 0.38 13.5 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Box $slide 0.75 1.92 5.7 4.35 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Base Gemma response pattern" 1.05 2.18 4.2 0.22 14 $Theme.BlueDark -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Passes low-level format checks" 1.05 2.66 2.6 0.2 10.5 $Theme.Green -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Valid JSON\nAction schema\nSelector syntax" 1.05 2.98 2.2 0.72 13 $Theme.Ink -Font "Aptos" | Out-Null
    Add-Text $slide "Misses workflow checks" 3.55 2.66 2.35 0.2 10.5 $Theme.Red -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Stable EIM selectors\nWorkflow navigation\nRequired actions\nCorrect order\nExact match" 3.55 2.98 2.4 1.1 13 $Theme.Ink -Font "Aptos" | Out-Null
    Add-Box $slide 1.05 4.48 4.85 1.13 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "Example: #member-search-3430" 1.28 4.76 4.1 0.2 16 $Theme.BlueDark -Bold -Font "Consolas" | Out-Null
    Add-Text $slide "Works once, brittle when UI-generated IDs change." 1.28 5.16 4.15 0.18 9.5 $Theme.Muted -Font "Segoe UI" | Out-Null
    Add-Box $slide 7.05 1.92 5.55 4.35 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Response Score Breakdown" 7.35 2.18 3.9 0.22 14 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    $checks = @("Valid JSON", "Action schema", "Selector validity", "Stable EIM selectors", "Workflow navigation", "Required actions", "Correct order", "Exact action match")
    $basePass = @(1,1,1,0,0,0,0,0)
    Add-Text $slide "Check" 7.35 2.62 2.15 0.16 8.5 $Theme.Muted -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Base" 10.2 2.62 0.8 0.16 8.5 $Theme.Muted -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "Tuned" 11.25 2.62 0.8 0.16 8.5 $Theme.Muted -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    for ($i=0; $i -lt $checks.Count; $i++) {
        $yy = 2.93 + ($i * 0.34)
        Add-Text $slide $checks[$i] 7.35 $yy 2.55 0.12 9.2 $Theme.Ink -Font "Segoe UI" | Out-Null
        Add-ScoreCell $slide $(if ($basePass[$i]) { "Pass" } else { "Miss" }) ([bool]$basePass[$i]) 10.1 ($yy - 0.04) 0.83
        Add-ScoreCell $slide "Pass" $true 11.2 ($yy - 0.04) 0.83
    }
    Add-Footer $slide $Index
    Add-Notes $slide "This is the baseline story. Base Gemma is not useless. It can often return JSON and it understands that the task is about clicking, typing, and extracting. But the failures are exactly the failures that matter for a browsing agent. It uses brittle IDs like member-search-3430, it can skip the workflow navigation step, and it may not preserve the required order. That is why this is a good fine-tuning candidate: the model already has general capability, but it needs to learn a precise behavior contract."
    return $slide
}

function Add-Slide5 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Where the small SLM succeeds natively - and where it fails"
    Add-Box $slide 0.72 1.55 5.7 4.9 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "Native strengths" 1.04 1.88 2.6 0.25 17 $Theme.Green -Bold -Font "Aptos Display" | Out-Null
    $strengths = @(
        "Understands healthcare-ish instructions",
        "Can parse compact HTML/DOM snippets",
        "Usually recognizes click/type/extract actions",
        "Can emit JSON when strongly prompted"
    )
    for ($i=0; $i -lt $strengths.Count; $i++) {
        $yy = 2.43 + ($i * 0.75)
        Add-Circle $slide 1.06 $yy 0.28 $Theme.Green | Out-Null
        Add-Text $slide "OK" 1.075 ($yy + 0.075) 0.25 0.08 5.5 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
        Add-Text $slide $strengths[$i] 1.48 ($yy - 0.03) 4.3 0.3 13 $Theme.Ink -Font "Segoe UI" | Out-Null
    }
    Add-Box $slide 6.95 1.55 5.7 4.9 $Theme.RedLight "none" -Rounded | Out-Null
    Add-Text $slide "Native gaps" 7.27 1.88 2.4 0.25 17 $Theme.Red -Bold -Font "Aptos Display" | Out-Null
    $gaps = @(
        "Chooses generated IDs instead of stable selectors",
        "May explain instead of returning only contract JSON",
        "Misses workflow navigation or pre-submit checks",
        "Order can drift on multi-step tasks"
    )
    for ($i=0; $i -lt $gaps.Count; $i++) {
        $yy = 2.43 + ($i * 0.75)
        Add-Circle $slide 7.29 $yy 0.28 $Theme.Red | Out-Null
        Add-Text $slide "!" 7.32 ($yy + 0.055) 0.22 0.08 8 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
        Add-Text $slide $gaps[$i] 7.7 ($yy - 0.03) 4.35 0.3 13 $Theme.Ink -Font "Segoe UI" | Out-Null
    }
    Add-Box $slide 4.78 5.92 3.75 0.78 $Theme.Graphite "none" -Rounded | Out-Null
    Add-Text $slide "Conclusion: promptable, but not yet dependable" 5.05 6.18 3.2 0.14 11.2 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "I would frame this carefully. A small SLM is attractive because it is cheaper to train, cheaper to deploy, and easier to specialize. The base model already understands the general shape of the problem, which is good. But for browser automation, near-misses still fail. A selector that looks valid but is unstable is not good enough. A response that has the right idea but adds prose is not good enough. The gap is behavior consistency, not raw knowledge."
    return $slide
}

function Add-Slide5EvalNumbers {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "What 37/112 and 71/112 mean"
    Add-Text $slide "These are not generic model accuracy numbers. They are a workflow scorecard across held-out browser-action prompts." 0.65 1.24 9.2 0.42 13.4 $Theme.Muted -Font "Aptos" | Out-Null

    Add-Box $slide 0.82 1.95 3.1 2.2 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Base Gemma" 1.12 2.25 2.4 0.25 15 $Theme.BlueDark -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "37/112" 1.08 2.78 2.5 0.48 31 $Theme.BlueDark -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Text $slide "Passed the easier format checks, but missed many workflow-contract checks." 1.15 3.45 2.35 0.4 10.4 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null

    Add-Box $slide 5.02 1.95 3.1 2.2 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "Fine-tuned Gemma" 5.32 2.25 2.45 0.25 15 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "71/112" 5.28 2.78 2.5 0.48 31 $Theme.Green -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Text $slide "Passed 34 more checks after learning the EIM action contract." 5.35 3.45 2.35 0.4 10.4 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null

    Add-Box $slide 9.22 1.95 2.55 2.2 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "Lift" 9.64 2.25 1.65 0.25 15 $Theme.BlueDark -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "+34" 9.62 2.82 1.65 0.44 31 $Theme.BlueDark -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Text $slide "About +30 percentage points on this narrow scorecard." 9.48 3.48 1.95 0.36 10 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null

    Add-Box $slide 0.92 4.7 3.05 1.15 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Why 112?" 1.18 4.96 1.3 0.2 13 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "16 held-out prompts x 7 scored checks = 112 possible pass points." 1.18 5.33 2.35 0.28 9.8 $Theme.Muted -Font "Segoe UI" | Out-Null

    Add-Box $slide 4.25 4.7 3.4 1.15 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "What gets scored?" 4.52 4.96 1.9 0.2 13 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "JSON validity, schema, selector policy, missing actions, action order, exact match, and selector validity." 4.52 5.32 2.65 0.34 9.2 $Theme.Muted -Font "Segoe UI" | Out-Null

    Add-Box $slide 8.0 4.7 3.55 1.15 $Theme.OrangeLight "none" -Rounded | Out-Null
    Add-Text $slide "How to say it" 8.28 4.96 1.7 0.2 13 "8A4B00" -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "This proves directional lift on a synthetic workflow benchmark, not production readiness." 8.28 5.32 2.8 0.32 9.4 "8A4B00" -Font "Segoe UI" | Out-Null

    Add-Footer $slide $Index
    Add-Notes $slide "Slide 5. I want to explain the numbers at the top of the app. Base Gemma winner eval is 37 out of 112. Fine-tuned winner eval is 71 out of 112. These are not generic model accuracy numbers. They are a workflow scorecard. The app evaluated 16 held-out browser-action prompts. For each prompt, it scored 7 checks, so 16 times 7 equals 112 possible pass points. Base Gemma passed 37 of those checks. Fine-tuned Gemma passed 71. That is a lift of 34 checks, or roughly 30 percentage points. The right way to say this is: fine-tuning materially improved the model's ability to follow the EIM action contract. It learned to return structured JSON, stable selectors, required actions, and better order more often. The important caveat is that this is a synthetic workflow benchmark. It is a strong directional demo result, not a production readiness claim."
    return $slide
}

function Add-Slide6 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Why fine-tuning is the right lever here"
    Add-Text $slide "We are not trying to teach the model medical facts. We are teaching it a repeatable output behavior: the Molina/EIM action contract." 0.65 1.25 8.0 0.42 13.5 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Box $slide 0.82 2.05 3.1 3.3 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Frozen base model" 1.08 2.35 2.3 0.25 16 $Theme.BlueDark -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Circle $slide 1.55 2.95 1.55 $Theme.BlueLight $Theme.Blue | Out-Null
    Add-Text $slide "Gemma" 1.91 3.45 0.82 0.18 16 $Theme.BlueDark -Bold -Align "Center" -Font "Aptos" | Out-Null
    Add-Text $slide "General language + code + web understanding stays intact." 1.25 4.75 2.25 0.35 10.5 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 5.1 1.78 3.1 3.85 $Theme.PurpleLight "none" -Rounded | Out-Null
    Add-Text $slide "LoRA adapter" 5.43 2.18 2.35 0.25 17 $Theme.Purple -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Box $slide 5.78 2.92 1.78 1.1 $Theme.Purple "none" -Rounded | Out-Null
    Add-Text $slide "~0.1%\ntrainable" 6.0 3.19 1.32 0.36 17 $Theme.White -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Text $slide "Small adapter learns selectors, ordering, and contract discipline." 5.55 4.58 2.0 0.4 10.5 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 9.35 2.05 3.1 3.3 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Tuned behavior" 9.68 2.35 2.35 0.25 16 $Theme.Green -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Box $slide 9.86 3.0 2.0 0.42 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "stable selectors" 10.09 3.15 1.5 0.1 8.5 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 9.86 3.55 2.0 0.42 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "right order" 10.28 3.7 1.0 0.1 8.5 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 9.86 4.1 2.0 0.42 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "no prose" 10.38 4.25 0.8 0.1 8.5 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Line $slide 3.95 3.68 5.02 3.68 $Theme.Blue 3 | Out-Null
    Add-Line $slide 8.23 3.68 9.3 3.68 $Theme.Green 3 | Out-Null
    Add-Callout $slide "Fits single A100 80GB" "bf16" 1.0 6.05 2.0 $Theme.Blue
    Add-Callout $slide "No full model retrain" "LoRA" 3.8 6.05 2.0 $Theme.Purple
    Add-Callout $slide "Adapter can be swapped" "per flow" 6.6 6.05 2.0 $Theme.TealDark
    Add-Callout $slide "Lower experiment cost" "fast" 9.4 6.05 2.0 $Theme.Green
    Add-Footer $slide $Index
    Add-Notes $slide "The important message is that fine-tuning here is behavioral. We are not asking Gemma to memorize Molina policy. We are teaching it how to respond when it sees a page state and an instruction. LoRA is a good fit because the base weights stay frozen and we only train a small adapter. That keeps the experiment cheap, makes it fit on one A100, and gives us a production-friendly pattern where different EIM workflows can eventually have different adapters."
    return $slide
}

function Add-Slide7 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Fine-tuning process flow used in this project"
    Add-Text $slide "The implementation is deliberately end-to-end: generate safe data, train on AzureML A100 compute, register the adapter, deploy, evaluate, and clean up." 0.65 1.22 9.1 0.42 13.2 $Theme.Muted -Font "Aptos" | Out-Null
    $colors = @($Theme.Blue, $Theme.TealDark, $Theme.Purple, $Theme.Orange, $Theme.Green, $Theme.Red)
    $steps = @(
        @{T="Generate synthetic JSONL"; B="DOM + instruction + gold assistant action plan."},
        @{T="Prepare data asset"; B="Register or package train and validation files."},
        @{T="Submit AML job"; B="A100 command job runs training/train.py."},
        @{T="Train LoRA adapter"; B="bf16 base model, rank/alpha adapters, SFTTrainer."},
        @{T="Register + deploy"; B="Adapter artifact becomes an AML model and endpoint."},
        @{T="Evaluate + cleanup"; B="Same prompts, base vs tuned, delete endpoint after demo."}
    )
    for ($i=0; $i -lt 6; $i++) {
        $row = if ($i -lt 3) { 0 } else { 1 }
        $col = if ($i -lt 3) { $i } else { 5 - $i }
        $x = 0.82 + ($col * 4.05)
        $y = 2.05 + ($row * 2.2)
        Add-Step $slide ($i + 1) $steps[$i].T $steps[$i].B $x $y 3.35 $colors[$i]
        if ($i -lt 2) { Add-Line $slide ($x + 3.38) ($y + 0.52) ($x + 3.82) ($y + 0.52) $colors[$i] 2.5 | Out-Null }
        if ($i -eq 2) { Add-Line $slide ($x + 1.68) ($y + 1.1) ($x + 1.68) ($y + 1.9) $colors[$i] 2.5 | Out-Null }
        if ($i -gt 3 -and $i -lt 6) { Add-Line $slide ($x - 0.44) ($y + 0.52) ($x - 0.02) ($y + 0.52) $colors[$i] 2.5 | Out-Null }
    }
    Add-Box $slide 0.95 6.64 11.25 0.34 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "Project files: data/generate_winner_data.py -> src/03_submit_training_job.py -> training/train.py -> src/04_register_and_deploy.py -> demo_app/app.py" 1.08 6.74 11.0 0.09 7.8 $Theme.BlueDark -Bold -Font "Consolas" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "This is the build flow I would walk through in the meeting. We start with deterministic synthetic examples. We prepare the training and validation data. The AzureML SDK submits a command job to the A100 cluster. The training script loads Gemma, applies LoRA adapters to attention and MLP projections, and trains with TRL SFTTrainer. The resulting adapter is registered as an AzureML model, deployed to a managed online endpoint, and tested in the Streamlit app. After the demo, the endpoint should be deleted to stop A100 billing."
    return $slide
}

function Add-Slide8 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Training data: synthetic browser-action examples"
    Add-Text $slide "The examples mirror the task shape without using Molina data: fake members, fake claims, deterministic seeds, and stable EIM selectors." 0.65 1.25 8.4 0.42 13.5 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Callout $slide "training records" "96" 0.78 1.95 2.0 $Theme.Blue
    Add-Callout $slide "validation records" "24" 3.05 1.95 2.0 $Theme.TealDark
    Add-Callout $slide "holdout eval prompts" "16" 5.32 1.95 2.0 $Theme.Purple
    Add-Callout $slide "real PHI used" "0" 7.59 1.95 2.0 $Theme.Green
    Add-Box $slide 0.78 3.35 5.88 2.9 "11100F" "605E5C" -Rounded | Out-Null
    Add-Text $slide "Sample input" 1.05 3.62 1.4 0.2 12 $Theme.BlueLight -Bold -Font "Segoe UI" | Out-Null
    $sampleInput = @'
DOM:
<button id='nav-1288-auth' data-eim-action='open-authorizations'>...
<input id='member-search-1288' data-eim-field='member-id' />
<button id='submit-review-1288' data-eim-action='complete-nurse-review'>...

Instruction:
Open authorization PA-2000109 for member M10000077 and complete nurse review
'@
    Add-Text $slide $sampleInput 1.05 4.02 5.25 1.75 9.2 "F3F2F1" -Font "Consolas" | Out-Null
    Add-Box $slide 7.02 3.35 5.52 2.9 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Gold assistant output" 7.32 3.62 2.0 0.2 12 $Theme.Green -Bold -Font "Segoe UI" | Out-Null
        $sampleOutput = @'
{
    "actions": [
        {"type":"click", "selector":"[data-eim-action='open-authorizations']"},
        {"type":"type", "selector":"[data-eim-field='member-id']", "value":"M10000077"},
        {"type":"click", "selector":"[data-eim-action='complete-nurse-review']"}
    ]
}
'@
    Add-Text $slide $sampleOutput 7.32 4.02 4.85 1.75 8.6 $Theme.Ink -Font "Consolas" | Out-Null
    Add-Box $slide 2.35 6.42 8.6 0.38 $Theme.OrangeLight "none" -Rounded | Out-Null
    Add-Text $slide "Why this data: teach stable selectors, exact JSON, workflow order, and reusable browser actions - not medical facts." 2.58 6.54 8.14 0.1 8.8 "8A4B00" -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "This is the data discipline slide. The data is intentionally synthetic. We used fake member IDs, fake authorization IDs, fake claims, and deterministic generators. That keeps us out of PHI and lets us focus on the behavior. Each example is a system, user, assistant turn. The user message contains the DOM and instruction. The assistant message is the exact JSON action plan we want the model to learn. The point is not to teach Molina policy; it is to teach the browser-action pattern."
    return $slide
}

function Add-Slide9 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Technical resources leveraged"
    Add-Text $slide "Foundry catalog assets plus AzureML SDK resources powered the demo. Gemma was not available through this serverless fine-tuning path, so training ran on AzureML managed A100 compute." 0.65 1.34 9.9 0.46 12.7 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Box $slide 0.78 1.92 2.15 1.1 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "Foundry / AML catalog" 1.0 2.22 1.68 0.18 11 $Theme.BlueDark -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "Gemma base model asset" 1.05 2.58 1.58 0.14 8 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 3.48 1.92 2.15 1.1 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "AzureML workspace" 3.78 2.22 1.5 0.18 11 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "jobs, data, models, lineage" 3.8 2.58 1.5 0.14 8 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 6.18 1.92 2.15 1.1 $Theme.PurpleLight "none" -Rounded | Out-Null
    Add-Text $slide "A100 compute" 6.63 2.22 1.15 0.18 11 $Theme.Purple -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "Standard_NC24ads_A100_v4" 6.42 2.58 1.65 0.14 7.4 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 8.88 1.92 2.15 1.1 $Theme.OrangeLight "none" -Rounded | Out-Null
    Add-Text $slide "Key Vault" 9.45 2.22 1.0 0.18 11 "8A4B00" -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "HF token / secrets" 9.35 2.58 1.15 0.14 8 $Theme.Muted -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Line $slide 2.95 2.47 3.45 2.47 $Theme.Blue 2.5 | Out-Null
    Add-Line $slide 5.65 2.47 6.15 2.47 $Theme.Green 2.5 | Out-Null
    Add-Line $slide 8.35 2.47 8.85 2.47 $Theme.Purple 2.5 | Out-Null
    Add-Box $slide 1.22 3.85 10.4 2.22 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "What the SDK scripts did" 1.55 4.18 2.8 0.22 14 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "src/02_prepare_data.py" 1.58 4.72 2.2 0.14 9.2 $Theme.BlueDark -Bold -Font "Consolas" | Out-Null
    Add-Text $slide "Registered synthetic train/validation data as an AML asset." 3.75 4.7 6.8 0.16 9.5 $Theme.Muted -Font "Segoe UI" | Out-Null
    Add-Text $slide "src/03_submit_training_job.py" 1.58 5.1 2.3 0.14 9.2 $Theme.BlueDark -Bold -Font "Consolas" | Out-Null
    Add-Text $slide "Submitted a command job to A100 compute with custom CUDA/Transformers/TRL environment." 3.75 5.08 6.95 0.16 9.5 $Theme.Muted -Font "Segoe UI" | Out-Null
    Add-Text $slide "src/04_register_and_deploy.py" 1.58 5.48 2.48 0.14 9.2 $Theme.BlueDark -Bold -Font "Consolas" | Out-Null
    Add-Text $slide "Registered adapter, packaged base+LoRA, and deployed a managed online endpoint." 3.75 5.46 6.7 0.16 9.5 $Theme.Muted -Font "Segoe UI" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "This slide explains the technical path. The reason we use AzureML is practical: Gemma is available as a catalog/base model path, but not as a Foundry serverless fine-tuning base for this demo. AzureML gives us the pieces we need: a governed workspace, data assets, command jobs, A100 managed compute, environments, model registration, and managed online endpoints. The SDK scripts are small control-plane wrappers around those resources."
    return $slide
}

function Add-Slide10 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Fine-tuning details: what trained on the A100"
    Add-Text $slide "The job runs inside AzureML. The laptop only submits and monitors; the GPU node loads the model, applies LoRA, trains, and writes artifacts." 0.65 1.25 8.8 0.42 13.2 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Box $slide 0.78 1.94 3.1 4.55 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Model load" 1.08 2.25 1.6 0.22 15 $Theme.BlueDark -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Gemma 4B-class SLM\nAzureML catalog mount\nbf16 on GPU\nscaled dot-product attention" 1.08 2.82 2.2 1.0 11.8 $Theme.Ink -Font "Aptos" | Out-Null
    Add-Box $slide 4.12 1.94 3.1 4.55 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "LoRA config" 4.42 2.25 1.6 0.22 15 $Theme.Purple -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "Rank 32\nAlpha 64\nDropout 0.05\nTarget: q/k/v/o + MLP projections" 4.42 2.82 2.25 1.1 11.8 $Theme.Ink -Font "Aptos" | Out-Null
    Add-Box $slide 7.45 1.94 2.95 4.55 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Trainer" 7.75 2.25 1.35 0.22 15 $Theme.Green -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "TRL SFTTrainer\nchat template\n8 epochs\nbatch 2 x grad accum 4\ncosine LR schedule" 7.75 2.82 2.0 1.28 11.8 $Theme.Ink -Font "Aptos" | Out-Null
    Add-Box $slide 10.65 1.94 1.85 4.55 $Theme.Graphite "none" -Rounded | Out-Null
    Add-Text $slide "Output" 11.05 2.25 1.0 0.22 15 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "LoRA adapter\nmetadata\nregistered model\ndeploy package" 10.88 2.96 1.37 1.05 10.8 $Theme.BlueLight -Bold -Align "Center" -Font "Aptos" | Out-Null
    Add-Line $slide 3.9 4.1 4.08 4.1 $Theme.Blue 2 | Out-Null
    Add-Line $slide 7.24 4.1 7.42 4.1 $Theme.Purple 2 | Out-Null
    Add-Line $slide 10.42 4.1 10.62 4.1 $Theme.Green 2 | Out-Null
    Add-Box $slide 1.38 6.76 10.55 0.28 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "Memory shape: base weights ~8GB, LoRA trainable params small, total fits comfortably on a single A100 80GB." 1.55 6.85 10.2 0.07 7.8 $Theme.BlueDark -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "Here I would go one layer deeper for the technical audience. The training job loads the base model and tokenizer, enables gradient checkpointing, and applies LoRA to the attention and MLP projection layers. The current winner profile uses a higher rank and alpha than the original simple demo: rank 32 and alpha 64, with eight epochs on a small synthetic dataset. TRL SFTTrainer applies the chat template and trains against the assistant JSON. The output is not a whole new full model first; it is a small adapter plus metadata, which we can register and deploy."
    return $slide
}

function Add-Slide11 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Live serving: one endpoint, two behaviors"
    Add-Text $slide "The Streamlit demo calls the same AzureML endpoint twice: base behavior with the adapter disabled, and fine-tuned behavior with the adapter enabled." 0.65 1.25 9.2 0.42 13.2 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Box $slide 0.82 2.05 3.35 3.85 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Base call" 1.14 2.37 1.3 0.22 15 $Theme.BlueDark -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "use_adapter=false" 1.14 2.86 1.9 0.16 10.5 $Theme.BlueDark -Bold -Font "Consolas" | Out-Null
    Add-Text $slide "Good general reasoning, but often brittle selectors and incomplete workflow steps." 1.14 3.34 2.45 0.8 12.5 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Box $slide 4.95 1.85 3.35 4.25 $Theme.Graphite "none" -Rounded | Out-Null
    Add-Text $slide "AzureML managed online endpoint" 5.35 2.22 2.55 0.44 15 $Theme.White -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Circle $slide 5.75 3.05 0.78 $Theme.Blue | Out-Null
    Add-Circle $slide 6.72 3.05 0.78 $Theme.Purple | Out-Null
    Add-Circle $slide 7.18 3.86 0.78 $Theme.Green | Out-Null
    Add-Circle $slide 6.2 3.86 0.78 $Theme.TealDark | Out-Null
    Add-Text $slide "base +\nLoRA" 6.17 3.48 1.15 0.38 15 $Theme.White -Bold -Align "Center" -Font "Aptos Display" | Out-Null
    Add-Text $slide "Deployment: ftadapter\nSKU: Standard_NC24ads_A100_v4\nMode: catalog base + LoRA adapter" 5.45 4.92 2.45 0.68 9.2 $Theme.BlueLight -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Box $slide 9.1 2.05 3.35 3.85 $Theme.Panel $Theme.Border -Rounded | Out-Null
    Add-Text $slide "Fine-tuned call" 9.42 2.37 1.75 0.22 15 $Theme.Green -Bold -Font "Segoe UI" | Out-Null
    Add-Text $slide "use_adapter=true" 9.42 2.86 1.9 0.16 10.5 $Theme.Green -Bold -Font "Consolas" | Out-Null
    Add-Text $slide "Learns the EIM contract: stable data-eim selectors, action order, and no prose." 9.42 3.34 2.45 0.8 12.5 $Theme.Muted -Font "Aptos" | Out-Null
    Add-Line $slide 4.18 3.86 4.9 3.86 $Theme.Blue 3 | Out-Null
    Add-Line $slide 8.32 3.86 9.05 3.86 $Theme.Green 3 | Out-Null
    Add-Box $slide 2.18 6.56 8.98 0.44 $Theme.GreenLight "none" -Rounded | Out-Null
    Add-Text $slide "Cost posture: one A100 endpoint for the demo, delete immediately afterward to stop hourly billing." 2.38 6.7 8.58 0.1 8.8 $Theme.Green -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "This is the serving story. The demo intentionally avoids paying for two GPU endpoints. The endpoint loads the base model and the adapter. The Streamlit app calls it once with the adapter disabled and once with the adapter enabled. That gives a clean side-by-side comparison. It also makes the cost conversation simple: the endpoint is the expensive part, so we run it for the meeting and then delete it."
    return $slide
}

function Add-Slide11FineTuneCode {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index
    Add-Title $slide "Fine-tuning in code: what actually changes"
    Add-Text $slide "The base Gemma weights stay mostly frozen. The training job learns a small LoRA adapter that changes how the model responds to this browser-action contract." 0.65 1.24 9.6 0.42 13.2 $Theme.Muted -Font "Aptos" | Out-Null

    $steps = @(
        @{N=1; T="Load base Gemma"; B="Transformers loads the catalog model in bf16 on the A100."; C=$Theme.Blue; Code="from_pretrained(...)"},
        @{N=2; T="Inject LoRA"; B="PEFT adds trainable adapter matrices to attention and MLP projections."; C=$Theme.Purple; Code="LoraConfig(r=32, alpha=64)"},
        @{N=3; T="Run SFT"; B="TRL SFTTrainer learns from messages: system, user DOM, assistant JSON."; C=$Theme.Green; Code="trainer = SFTTrainer(...)"},
        @{N=4; T="Save adapter"; B="Only the adapter and metadata are saved, then registered and deployed."; C=$Theme.Orange; Code="save_pretrained(adapter)"}
    )
    for ($i = 0; $i -lt $steps.Count; $i++) {
        $x = 0.78 + ($i * 3.05)
        Add-Box $slide $x 2.05 2.72 3.9 $Theme.Panel $Theme.Border -Rounded | Out-Null
        Add-Circle $slide ($x + 0.18) 2.28 0.48 $steps[$i].C | Out-Null
        Add-Text $slide ([string]$steps[$i].N) ($x + 0.195) 2.36 0.45 0.12 10 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
        Add-Text $slide $steps[$i].T ($x + 0.78) 2.28 1.68 0.25 12.5 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
        Add-Text $slide $steps[$i].B ($x + 0.24) 2.9 2.2 0.72 10.2 $Theme.Muted -Font "Segoe UI" | Out-Null
        Add-Box $slide ($x + 0.24) 4.05 2.18 0.62 "11100F" "none" -Rounded | Out-Null
        Add-Text $slide $steps[$i].Code ($x + 0.35) 4.28 1.98 0.12 7.7 $Theme.BlueLight -Font "Consolas" | Out-Null
        if ($i -lt 3) { Add-Line $slide ($x + 2.74) 4.0 ($x + 3.0) 4.0 $steps[$i].C 2.5 | Out-Null }
    }

    Add-Box $slide 1.05 6.35 11.15 0.48 $Theme.BlueLight "none" -Rounded | Out-Null
    Add-Text $slide "Plain English: we do not overwrite Gemma. We attach a small learned adapter that nudges it toward stable selectors, strict JSON, and correct workflow order." 1.28 6.5 10.7 0.12 9.2 $Theme.BlueDark -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Footer $slide $Index
    Add-Notes $slide "This slide is the code-level fine-tuning explanation. I will replace these notes with the consolidated line-by-line talk track before saving the deck."
    return $slide
}

function Add-Slide12 {
    param($Presentation, [int]$Index)
    $slide = New-Slide $Presentation $Index $Theme.Graphite
    Add-Circle $slide -0.7 4.7 3.2 $Theme.Blue "none" 0.2 | Out-Null
    Add-Circle $slide 10.8 -0.95 3.0 $Theme.Teal "none" 0.25 | Out-Null
    Add-Text $slide "How the fine-tuned model solves the problem" 0.72 0.72 7.4 0.65 31 $Theme.White -Bold -Font "Aptos Display" | Out-Null
    Add-Text $slide "It turns the ask into a dependable workflow contract instead of a plausible web-action guess." 0.75 1.58 6.4 0.42 14 $Theme.BlueLight -Font "Aptos" | Out-Null
    $wins = @(
        @{T="Stable selectors"; B="Uses [data-eim-*] contract selectors instead of generated IDs."; C=$Theme.Blue},
        @{T="Workflow order"; B="Opens the right workspace, fills fields, runs checks, submits in sequence."; C=$Theme.TealDark},
        @{T="Machine-readable"; B="Returns JSON only, so downstream automation can parse and replay."; C=$Theme.Green},
        @{T="Governed path"; B="Synthetic data, AzureML lineage, model registration, endpoint cleanup."; C=$Theme.Orange}
    )
    for ($i=0; $i -lt 4; $i++) {
        $x = 0.88 + (($i % 2) * 5.85)
        $y = 2.45 + ([math]::Floor($i / 2) * 1.55)
        Add-Box $slide $x $y 5.2 1.1 "FFFFFF" "none" -Rounded -Transparency 0.03 | Out-Null
        Add-Circle $slide ($x + 0.22) ($y + 0.25) 0.48 $wins[$i].C | Out-Null
        Add-Text $slide ([string]($i + 1)) ($x + 0.235) ($y + 0.33) 0.45 0.12 10 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
        Add-Text $slide $wins[$i].T ($x + 0.88) ($y + 0.18) 3.9 0.18 13.5 $Theme.Ink -Bold -Font "Segoe UI" | Out-Null
        Add-Text $slide $wins[$i].B ($x + 0.88) ($y + 0.52) 3.9 0.34 8.8 $Theme.Muted -Font "Segoe UI" | Out-Null
    }
    Add-Box $slide 2.0 6.18 9.35 0.55 $Theme.BlueDark "none" -Rounded | Out-Null
    Add-Text $slide "Recommended next step: pick one real EIM flow, define graders, curate safe examples, rerun the same baseline -> fine-tune -> eval loop." 2.22 6.38 8.9 0.11 9.5 $Theme.White -Bold -Align "Center" -Font "Segoe UI" | Out-Null
    Add-Text $slide "Microsoft AI + AzureML | June 2026" 0.78 7.08 3.2 0.18 8.5 "C8C6C4" -Font "Segoe UI" | Out-Null
    Add-Notes $slide "I would close by saying: the fine-tuned model solves the problem by learning the contract. It does not make the system production-ready by itself, and it does not replace retrieval, policy governance, or human review. But it shows that a small model can be specialized for browser-action behavior. The next step is not to broaden the assistant. The next step is to select one high-value EIM workflow, define graders up front, use safe training data, and run the same evaluation loop with a clear pass threshold and cost ceiling."
    return $slide
}

$builders = @(
    ${function:Add-Slide1},
    ${function:Add-Slide2},
    ${function:Add-Slide3},
    ${function:Add-Slide4},
    ${function:Add-Slide5EvalNumbers},
    ${function:Add-Slide5},
    ${function:Add-Slide6},
    ${function:Add-Slide7},
    ${function:Add-Slide8},
    ${function:Add-Slide9},
    ${function:Add-Slide10},
    ${function:Add-Slide11FineTuneCode},
    ${function:Add-Slide11},
    ${function:Add-Slide12}
)

$TalkTracks = @(
    (New-TalkTrack @(
        "Slide 1. I will start with the headline: this is a Gemma 4B-class fine-tuning demo for a browser-action agent.",
        "The business question is whether a small open model can learn a reliable EIM workflow behavior.",
        "The demo uses AzureML managed compute, synthetic data only, and a LoRA adapter.",
        "The output we care about is not prose. It is a JSON action plan that another system can execute.",
        "I will walk through the baseline, the fine-tuning method, the data, the Azure resources, and the before-after result."
    ))
    (New-TalkTrack @(
        "Slide 2. The problem is that browsing agents need repeatable actions, not just good-sounding answers.",
        "The user gives a goal, such as opening a prior authorization and submitting it after a policy check.",
        "The model sees a compact page state, usually a DOM snippet with both generated IDs and stable attributes.",
        "The model must return the action contract: click, type, or extract in strict JSON.",
        "This matters because Molina needs repeatable, auditable, low-variance workflow behavior."
    ))
    (New-TalkTrack @(
        "Slide 3. This demo is scoped narrowly on purpose.",
        "We test a workflow contract: DOM plus instruction in, JSON action plan out.",
        "We use base Gemma as the small-model baseline to see what it can do before training.",
        "We use synthetic healthcare-shaped data so no Molina PHI is involved.",
        "We score objective checks: valid JSON, schema, stable selectors, workflow navigation, required actions, and order.",
        "The Azure path is AzureML because this Gemma fine-tuning route is not using Foundry serverless fine-tuning."
    ))
    (New-TalkTrack @(
        "Slide 4. Base Gemma is not bad, but it misses the contract we need.",
        "It can often produce valid JSON and understand that the task involves clicking, typing, and extracting.",
        "Where it fails is the workflow discipline.",
        "It may choose generated IDs like member-search-3430 instead of stable data-eim selectors.",
        "It may skip opening the correct workspace or miss the exact order.",
        "That is why prompting alone is not the full answer for this demo."
    ))
    (New-TalkTrack @(
        "Slide 5. I want to explain the numbers at the top of the app.",
        "Base Gemma winner eval is 37 out of 112.",
        "Fine-tuned winner eval is 71 out of 112.",
        "These are not generic model accuracy numbers; they are a workflow scorecard.",
        "The app evaluated 16 held-out browser-action prompts, and each prompt had 7 scored checks, so 16 times 7 equals 112 possible pass points.",
        "Base Gemma passed 37 of those checks, while fine-tuned Gemma passed 71.",
        "That is a lift of 34 checks, or roughly 30 percentage points.",
        "The right way to phrase this is: fine-tuning materially improved the model's ability to follow the EIM action contract.",
        "The caveat is that this is a synthetic workflow benchmark, not a production readiness claim."
    ))
    (New-TalkTrack @(
        "Slide 6. The small SLM succeeds natively on general understanding.",
        "It can parse healthcare-ish instructions and compact HTML or DOM snippets.",
        "It usually understands click, type, and extract as action types.",
        "But native behavior is still inconsistent for automation.",
        "For a browser agent, a near miss still fails if the selector is brittle or the response includes extra prose.",
        "So the measured gap is behavior consistency, not raw model knowledge."
    ))
    (New-TalkTrack @(
        "Slide 7. Fine-tuning is the right lever because the gap is behavioral.",
        "We are not teaching Molina medical policy to the model.",
        "We are teaching the model how to respond when it sees a page state and a user instruction.",
        "LoRA keeps the base Gemma model frozen and trains a small adapter on top.",
        "That adapter learns stable selectors, workflow ordering, and JSON-only discipline.",
        "This keeps the experiment cheaper and makes the behavior swappable by workflow later."
    ))
    (New-TalkTrack @(
        "Slide 8. Here is the end-to-end process flow.",
        "First, we generate deterministic synthetic JSONL examples.",
        "Second, we prepare or package the data for AzureML.",
        "Third, the AzureML SDK submits a command job to the A100 cluster.",
        "Fourth, training.py loads Gemma, applies LoRA, and runs supervised fine-tuning.",
        "Fifth, the adapter is registered and deployed.",
        "Finally, the Streamlit app compares base and tuned behavior on the same prompts."
    ))
    (New-TalkTrack @(
        "Slide 9. This is the data used for training.",
        "The current winner profile uses 96 training records, 24 validation records, and 16 holdout eval prompts.",
        "Each record is a messages object: system instruction, user DOM plus instruction, and assistant JSON answer.",
        "The values are fake: fake member IDs, fake authorization IDs, and fake claims.",
        "The reason for synthetic data is safety and control.",
        "We are proving the workflow pattern without exposing Molina production data."
    ))
    (New-TalkTrack @(
        "Slide 10. These are the technical resources behind the demo.",
        "Foundry and AzureML catalog assets provide the Gemma base model reference.",
        "AzureML provides the workspace, jobs, data assets, model registry, lineage, and managed online endpoint.",
        "A100 compute runs the actual training job.",
        "Key Vault is the production pattern for gated model tokens and secrets.",
        "The SDK scripts are control-plane wrappers: prepare data, submit training, register the adapter, and deploy the endpoint."
    ))
    (New-TalkTrack @(
        "Slide 11. This is what trains on the A100.",
        "The laptop does not fine-tune the model. It only submits and monitors the AzureML job.",
        "Inside the job, Transformers loads the Gemma base model in bf16.",
        "PEFT applies LoRA with rank 32 and alpha 64 in the current winner profile.",
        "The target modules are attention projections and MLP projections: q, k, v, o, gate, up, and down.",
        "TRL SFTTrainer applies the chat template and trains on the assistant JSON examples.",
        "The output is a LoRA adapter plus metadata, not a full model retrain."
    ))
    (New-TalkTrack @(
        "Slide 12. This is the fine-tuning code path in plain English.",
        "Step one, Transformers loads the base Gemma model from the catalog mount or model path.",
        "Step two, PEFT injects LoRA trainable matrices into selected layers while the base weights stay frozen.",
        "Step three, SFTTrainer trains against the message records: system, user DOM, and assistant JSON.",
        "Step four, the job saves the adapter to outputs/lora_adapter.",
        "The key point is that fine-tuning changes the response behavior through the adapter, not by rewriting the whole base model."
    ))
    (New-TalkTrack @(
        "Slide 13. The live serving pattern uses one endpoint and two behaviors.",
        "The endpoint loads the base model and the LoRA adapter.",
        "When use_adapter is false, we see base Gemma behavior.",
        "When use_adapter is true, we see the fine-tuned behavior.",
        "That gives a clean side-by-side comparison without paying for two GPU endpoints.",
        "After the demo, delete the endpoint to stop A100 hourly billing."
    ))
    (New-TalkTrack @(
        "Slide 14. The conclusion is that the fine-tuned model solves the narrow contract better.",
        "It learns to use stable data-eim selectors instead of generated IDs.",
        "It learns workflow order, such as opening the workspace before acting inside it.",
        "It keeps the response machine-readable by returning JSON only.",
        "It remains governed through synthetic data, AzureML lineage, model registration, and endpoint cleanup.",
        "The recommended next step is one real Molina workflow, safe examples, agreed graders, and the same baseline to fine-tune to eval loop."
    ))
)

$powerPoint = $null
$presentation = $null
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $powerPoint.Visible = $msoTrue
    $presentation = $powerPoint.Presentations.Add()
    $presentation.PageSetup.SlideWidth = Inch $SlideW
    $presentation.PageSetup.SlideHeight = Inch $SlideH
    try { $presentation.BuiltInDocumentProperties("Author").Value = "Jay Padhya" } catch { }

    for ($i = 0; $i -lt $builders.Count; $i++) {
        & $builders[$i] $presentation ($i + 1) | Out-Null
    }

    for ($i = 1; $i -le $TalkTracks.Count; $i++) {
        Add-Notes $presentation.Slides.Item($i) $TalkTracks[$i - 1]
    }

    if (Test-Path $OutputPath) { Remove-Item -Force $OutputPath }
    $presentation.SaveAs($OutputPath)

    if (Test-Path $ExportDir) {
        Get-ChildItem -Path $ExportDir -Filter "*.PNG" -ErrorAction SilentlyContinue | Remove-Item -Force
    }
    $presentation.Export($ExportDir, "PNG", 1600, 900)

    Write-Output "Wrote $OutputPath"
    Write-Output "Exported slide images to $ExportDir"
    Write-Output "Slides: $($builders.Count)"
}
finally {
    if ($presentation -ne $null) {
        try { $presentation.Close() | Out-Null } catch { }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) | Out-Null
    }
    if ($powerPoint -ne $null) {
        try { $powerPoint.Quit() | Out-Null } catch { }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) | Out-Null
    }
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}