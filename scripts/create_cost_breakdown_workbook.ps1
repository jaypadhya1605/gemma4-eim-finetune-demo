$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $Root "demo"
$Out = Join-Path $OutDir "gemma-a100-cost-breakdown.xlsx"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Currency0 = '$#,##0;($#,##0);-'
$Currency2 = '$#,##0.00;($#,##0.00);-'
$Number1 = '#,##0.0'

function Set-CellValue($Sheet, [int]$Row, [int]$Col, $Value) {
    $cell = $Sheet.Cells.Item($Row, $Col)
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        $cell.Value2 = [double]$Value
    }
    elseif ($Value -is [string] -and $Value.StartsWith('=')) {
        $cell.Formula = $Value
    }
    else {
        $cell.Value2 = [string]$Value
    }
}

function Set-Row($Sheet, [int]$Row, [object[]]$Values) {
    for ($i = 0; $i -lt $Values.Count; $i++) {
        Set-CellValue $Sheet $Row ($i + 1) $Values[$i]
    }
}

function Add-Header($Sheet, [string]$Title, [int]$Cols = 8) {
    Set-CellValue $Sheet 1 1 $Title
    $range = $Sheet.Range($Sheet.Cells.Item(1,1), $Sheet.Cells.Item(1,$Cols))
    $range.Merge() | Out-Null
    $range.Font.Bold = $true
    $range.Font.Size = 18
    $range.Font.Color = 16777215
    $range.Interior.Color = 8210719
    $range.HorizontalAlignment = -4108
}

function Format-Table($Sheet, [string]$RangeAddress) {
    $range = $Sheet.Range($RangeAddress)
    $range.Borders.LineStyle = 1
    $range.Borders.Color = 14277081
    $range.VerticalAlignment = -4160
}

$excel = $null
$wb = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $wb = $excel.Workbooks.Add()
    while ($wb.Worksheets.Count -lt 8) { $wb.Worksheets.Add() | Out-Null }

    $sheetNames = @(
        'Executive Summary',
        'Assumptions',
        'GPU Pricing',
        'Endpoint Usage',
        'Fine-tuning Experiments',
        'Storage_Support',
        'Resource Detail',
        'Sources Caveats'
    )
    for ($i = 1; $i -le $sheetNames.Count; $i++) { $wb.Worksheets.Item($i).Name = $sheetNames[$i-1] }

    # Assumptions
    $ws = $wb.Worksheets.Item('Assumptions')
    Add-Header $ws 'Editable Assumptions' 6
    Set-Row $ws 3 @('Category','Assumption','Gemma 4B','Gemma 31B','Unit','Notes')
    $ws.Range('A3:F3').Font.Bold = $true
    $ws.Range('A3:F3').Interior.Color = 15652797
    $assumptions = @(
        @('General','Region','eastus2','eastus2','text','Azure Retail Prices queried for East US 2'),
        @('General','Monthly hours',730,730,'hours','Used for always-on endpoint scenario'),
        @('General','Demo endpoint hours',4,4,'hours','Short customer demo window'),
        @('General','Pilot endpoint hours/month',80,80,'hours','4 hours/day x 20 business days'),
        @('General','Hot LRS storage price',0.0184,0.0184,'$/GB-month','Editable assumption; storage query did not return a clean SKU result'),
        @('General','Key Vault + App Insights estimate',6,6,'$/month','Small supporting services estimate'),
        @('Training','Fine-tune experiments',10,5,'runs','Expected iteration count'),
        @('Training','Hours per fine-tune run',1,6,'hours/run','4B quick LoRA; 31B distributed LoRA estimate'),
        @('Training','Training GPU hourly rate',3.673,14.692,'$/hour','4B: NC24ads A100; 31B: NC96ads A100 4x'),
        @('Endpoint','Endpoint GPU hourly rate',3.673,7.346,'$/hour','4B: 1x A100; 31B default: 2x A100 endpoint'),
        @('Storage','Training data GB',1,5,'GB','Synthetic/curated JSONL, snapshots, validation'),
        @('Storage','Model artifacts/checkpoints GB',30,280,'GB','Base/model packages, adapters, checkpoints'),
        @('Storage','Logs and telemetry GB',5,25,'GB','AzureML logs, metrics, app traces')
    )
    for ($i = 0; $i -lt $assumptions.Count; $i++) { Set-Row $ws ($i + 4) $assumptions[$i] }
    $ws.Range('C4:D16').Font.Color = 16711680
    $ws.Range('C8:D16').NumberFormat = $Number1
    Format-Table $ws 'A3:F16'

    # GPU Pricing
    $ws = $wb.Worksheets.Item('GPU Pricing')
    Add-Header $ws 'Azure GPU Pricing Inputs' 8
    Set-Row $ws 3 @('Use Case','Model','SKU','GPU profile','OS','Region','Hourly price','Source / Notes')
    $ws.Range('A3:H3').Font.Bold = $true
    $ws.Range('A3:H3').Interior.Color = 15652797
    $gpuRows = @(
        @('4B train + endpoint','Gemma 4B','Standard_NC24ads_A100_v4','1x A100 80GB','Linux','eastus2',3.673,'Azure Retail Pricing, Consumption, queried Jun 2026'),
        @('31B endpoint minimum','Gemma 31B','Standard_NC48ads_A100_v4','2x A100 80GB','Linux','eastus2',7.346,'Azure Retail Pricing, Consumption, queried Jun 2026'),
        @('31B training / safe endpoint','Gemma 31B','Standard_NC96ads_A100_v4','4x A100 80GB','Linux','eastus2',14.692,'Azure Retail Pricing, Consumption, queried Jun 2026'),
        @('31B high-memory/distributed','Gemma 31B','Standard_ND96amsr_A100_v4','8x A100 80GB','Linux','eastus2',32.77,'Azure Retail Pricing, Consumption, queried Jun 2026'),
        @('4B spot reference','Gemma 4B','Standard_NC24ads_A100_v4 Spot','1x A100 80GB','Linux','eastus2',0.948736,'Spot price varies; not for reliable demo endpoint'),
        @('31B spot reference','Gemma 31B','Standard_NC96ads_A100_v4 Spot','4x A100 80GB','Linux','eastus2',3.794944,'Spot price varies; interruptible experiments only')
    )
    for ($i = 0; $i -lt $gpuRows.Count; $i++) { Set-Row $ws ($i + 4) $gpuRows[$i] }
    $ws.Range('G4:G9').NumberFormat = $Currency2
    Format-Table $ws 'A3:H9'

    # Executive Summary
    $ws = $wb.Worksheets.Item('Executive Summary')
    Add-Header $ws 'Gemma A100 Cost Breakdown - Summary' 8
    Set-Row $ws 3 @('Model','Training runs','Training cost','Demo endpoint cost','Pilot endpoint cost/month','24x7 endpoint cost/month','Storage + support/month','Controlled pilot total')
    $ws.Range('A3:H3').Font.Bold = $true
    $ws.Range('A3:H3').Interior.Color = 15652797
    Set-Row $ws 4 @('Gemma 4B','=Assumptions!C10','=Assumptions!C10*Assumptions!C11*Assumptions!C12','=Assumptions!C13*Assumptions!C6','=Assumptions!C13*Assumptions!C7','=Assumptions!C13*Assumptions!C5','=Storage_Support!F4','=C4+E4+G4')
    Set-Row $ws 5 @('Gemma 31B','=Assumptions!D10','=Assumptions!D10*Assumptions!D11*Assumptions!D12','=Assumptions!D13*Assumptions!D6','=Assumptions!D13*Assumptions!D7','=Assumptions!D13*Assumptions!D5','=Storage_Support!F5','=C5+E5+G5')
    $ws.Range('C4:H5').NumberFormat = $Currency0
    Set-CellValue $ws 7 1 'Key message'
    Set-CellValue $ws 7 2 'Training is low-cost compared with idle endpoint hosting. Gemma 31B moves from single-A100 economics to multi-A100 economics.'
    $ws.Range('B7:H8').Merge() | Out-Null
    $ws.Range('B7').WrapText = $true
    Format-Table $ws 'A3:H8'

    # Endpoint Usage
    $ws = $wb.Worksheets.Item('Endpoint Usage')
    Add-Header $ws 'Endpoint Usage Scenarios' 9
    Set-Row $ws 3 @('Model','Endpoint profile','SKU','Hourly price','4h demo','40h prep week','80h pilot month','730h 24x7 month','Notes')
    $ws.Range('A3:I3').Font.Bold = $true
    $ws.Range('A3:I3').Interior.Color = 15652797
    $endpointRows = @(
        @('Gemma 4B','Default','Standard_NC24ads_A100_v4',3.673,'=D4*4','=D4*40','=D4*80','=D4*730','1x A100 endpoint used by demo'),
        @('Gemma 31B','Cost-optimized','Standard_NC48ads_A100_v4',7.346,'=D5*4','=D5*40','=D5*80','=D5*730','2x A100; default pilot inference estimate'),
        @('Gemma 31B','Safer capacity','Standard_NC96ads_A100_v4',14.692,'=D6*4','=D6*40','=D6*80','=D6*730','4x A100; more headroom'),
        @('Gemma 31B','High-memory distributed','Standard_ND96amsr_A100_v4',32.77,'=D7*4','=D7*40','=D7*80','=D7*730','8x A100; use only if needed')
    )
    for ($i = 0; $i -lt $endpointRows.Count; $i++) { Set-Row $ws ($i + 4) $endpointRows[$i] }
    $ws.Range('D4:H7').NumberFormat = $Currency0
    Format-Table $ws 'A3:I7'

    # Fine-tuning Experiments
    $ws = $wb.Worksheets.Item('Fine-tuning Experiments')
    Add-Header $ws 'Fine-tuning Experiment Cost' 8
    Set-Row $ws 3 @('Model','Training profile','SKU','Hourly price','Hours/run','Runs','Training compute cost','Notes')
    $ws.Range('A3:H3').Font.Bold = $true
    $ws.Range('A3:H3').Interior.Color = 15652797
    $ftRows = @(
        @('Gemma 4B','LoRA SFT demo','Standard_NC24ads_A100_v4',3.673,1,10,'=D4*E4*F4','Current demo profile; 30-60 min per run'),
        @('Gemma 31B','LoRA SFT 4x A100','Standard_NC96ads_A100_v4',14.692,6,5,'=D5*E5*F5','Recommended starting estimate for 31B'),
        @('Gemma 31B','LoRA SFT 8x A100','Standard_ND96amsr_A100_v4',32.77,4,5,'=D6*E6*F6','Fallback if memory/throughput needs more headroom')
    )
    for ($i = 0; $i -lt $ftRows.Count; $i++) { Set-Row $ws ($i + 4) $ftRows[$i] }
    $ws.Range('D4:D6').NumberFormat = $Currency2
    $ws.Range('G4:G6').NumberFormat = $Currency0
    Format-Table $ws 'A3:H6'

    # Storage Support
    $ws = $wb.Worksheets.Item('Storage_Support')
    Add-Header $ws 'Storage and Supporting Services' 7
    Set-Row $ws 3 @('Model','Training data GB','Model artifacts/checkpoints GB','Logs/telemetry GB','Storage cost/month','Storage + support/month','Notes')
    $ws.Range('A3:G3').Font.Bold = $true
    $ws.Range('A3:G3').Interior.Color = 15652797
    Set-Row $ws 4 @('Gemma 4B','=Assumptions!C14','=Assumptions!C15','=Assumptions!C16','=SUM(B4:D4)*Assumptions!C8','=E4+Assumptions!C9','Small JSONL data; model artifacts dominate storage.')
    Set-Row $ws 5 @('Gemma 31B','=Assumptions!D14','=Assumptions!D15','=Assumptions!D16','=SUM(B5:D5)*Assumptions!D8','=E5+Assumptions!D9','Larger base weights/checkpoints increase artifact storage.')
    $ws.Range('B4:D5').NumberFormat = '#,##0'
    $ws.Range('E4:F5').NumberFormat = $Currency0
    Format-Table $ws 'A3:G5'

    # Resource Detail
    $ws = $wb.Worksheets.Item('Resource Detail')
    Add-Header $ws 'Detailed Azure Resources and Cost Drivers' 7
    Set-Row $ws 3 @('Resource','Applies to','SKU / Tier','Cost driver','Gemma 4B estimate','Gemma 31B estimate','Notes')
    $ws.Range('A3:G3').Font.Bold = $true
    $ws.Range('A3:G3').Interior.Color = 15652797
    $detailRows = @(
        @('AzureML workspace','Both','Workspace','Lineage/jobs/assets','No direct base charge','No direct base charge','Compute/storage are billed separately'),
        @('Training compute','4B','NC24ads_A100_v4','GPU hours','$37 for 10 one-hour runs','n/a','Autoscale to zero after jobs'),
        @('Training compute','31B','NC96ads_A100_v4','GPU hours','n/a','$441 for 5 six-hour runs','31B should use multi-GPU for practical LoRA SFT'),
        @('Online endpoint','4B','NC24ads_A100_v4','Endpoint uptime','$294/mo at 80h; $2,681/mo 24x7','n/a','Delete after demo'),
        @('Online endpoint','31B','NC48ads_A100_v4','Endpoint uptime','n/a','$588/mo at 80h; $5,363/mo 24x7','2x A100 default estimate'),
        @('Storage account','Both','Hot LRS assumption','GB-month','~$1 storage + support ~$7/mo','~$6 storage + support ~$12/mo','Dataset tiny; artifacts dominate'),
        @('Key Vault','Both','Standard','Operations/secrets','Included in support estimate','Included in support estimate','HF token / secrets'),
        @('App Insights / Log Analytics','Both','PAYG','Ingested logs','Included in support estimate','Included in support estimate','Grows with verbose endpoint telemetry')
    )
    for ($i = 0; $i -lt $detailRows.Count; $i++) { Set-Row $ws ($i + 4) $detailRows[$i] }
    Format-Table $ws 'A3:G11'

    # Sources Caveats
    $ws = $wb.Worksheets.Item('Sources Caveats')
    Add-Header $ws 'Sources, Caveats, and Recommendations' 2
    Set-Row $ws 3 @('Topic','Detail')
    $ws.Range('A3:B3').Font.Bold = $true
    $ws.Range('A3:B3').Interior.Color = 15652797
    $notes = @(
        @('Pricing source','Azure Retail Pricing API via Azure MCP, region eastus2, USD, queried June 2026.'),
        @('Dominant cost','GPU endpoint uptime dominates. Training is cheap if jobs are short and compute scales to zero.'),
        @('Gemma 4B','Current demo uses 1x A100 for LoRA training and endpoint serving.'),
        @('Gemma 31B','31B estimates assume multi-GPU A100. Single A100 is not recommended for fine-tuning; inference may fit tightly but has less headroom.'),
        @('Storage','Storage cost is modeled as editable Hot LRS assumption because the retail query did not return a clean storage SKU result in this session.'),
        @('Not included','Enterprise networking, private endpoints, APIM, CI/CD, engineering labor, reserved instances, taxes, support plans.'),
        @('Cost control','Train, deploy briefly, evaluate, then delete endpoint. Use scheduled uptime for pilots.')
    )
    for ($i = 0; $i -lt $notes.Count; $i++) { Set-Row $ws ($i + 4) $notes[$i] }
    Format-Table $ws 'A3:B10'
    $ws.Columns.Item(2).ColumnWidth = 110
    $ws.Range('B:B').WrapText = $true

    foreach ($sheet in $wb.Worksheets) {
        $sheet.Cells.Font.Name = 'Arial'
        $sheet.Cells.VerticalAlignment = -4160
        $sheet.UsedRange.WrapText = $true
        $sheet.UsedRange.Borders.LineStyle = 1
        $sheet.UsedRange.Borders.Color = 14277081
        $sheet.Columns.AutoFit() | Out-Null
    }
    $wb.Worksheets.Item('Executive Summary').Activate() | Out-Null
    $excel.CalculateFullRebuild()
    if (Test-Path $Out) { Remove-Item -Force $Out }
    $wb.SaveAs($Out, 51)
    Write-Output "Wrote $Out"
}
finally {
    if ($wb -ne $null) { try { $wb.Close($true) | Out-Null } catch { } }
    if ($excel -ne $null) { try { $excel.Quit() | Out-Null } catch { } }
    if ($wb -ne $null) { [Runtime.InteropServices.Marshal]::ReleaseComObject($wb) | Out-Null }
    if ($excel -ne $null) { [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
