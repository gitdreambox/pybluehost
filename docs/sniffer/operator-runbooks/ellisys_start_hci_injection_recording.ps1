
$ErrorActionPreference = 'Stop'
[Reflection.Assembly]::LoadFrom('C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\RemoteControl\Ice.dll') | Out-Null
[Reflection.Assembly]::LoadFrom('C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\RemoteControl\EllisysAnalyzerBluetoothRemoteControlPlugin.dll') | Out-Null
$communicator = [Ice.Util]::initialize()
try {
  $proxy = $communicator.stringToProxy('Ellisys.AnalyzerRemoteControl.Bluetooth:tcp -h localhost -p 46148')
  $remote = [Ellisys.Platform.NetworkRemoteControl.Analyzer.BluetoothAnalyzerRemoteControlPrxHelper]::checkedCast($proxy)
  if ($null -eq $remote) { throw 'Failed to cast Ellisys remote control proxy' }
  if ($remote.IsRecording()) { $remote.AbortRecordingAndDiscardTraceFile() }
  try {
    $sources = @($remote.GetAvailableDataSources())
    Write-Host ('Available data sources: ' + ($sources -join ', '))
  } catch {
    Write-Host ('GetAvailableDataSources skipped: ' + $_.Exception.Message)
  }
  try {
    $remote.SelectDataSource('injection')
    Write-Host 'Selected data source: injection'
  } catch {
    Write-Host ('SelectDataSource(injection) skipped: ' + $_.Exception.Message)
  }
  try {
    Write-Host ('Current data source: ' + $remote.GetSelectedDataSource())
  } catch {
    Write-Host ('GetSelectedDataSource skipped: ' + $_.Exception.Message)
  }
  try {
    $remote.CancelUserInteraction()
  } catch {
    Write-Host ('CancelUserInteraction before StartRecording skipped: ' + $_.Exception.Message)
  }
  try {
    $remote.StartRecording()
  } catch {
    Write-Host ('StartRecording retry after pending interaction: ' + $_.Exception.Message)
    if (-not $remote.IsRecording()) {
      try { $remote.CancelUserInteraction() } catch { Write-Host ('CancelUserInteraction retry skipped: ' + $_.Exception.Message) }
      Start-Sleep -Seconds 1
      try {
        $remote.StartRecording()
      } catch {
        if (-not $remote.IsRecording()) { throw }
        Write-Host 'StartRecording reported an error, but Ellisys is already recording; continuing.'
      }
    } else {
      Write-Host 'StartRecording reported an error, but Ellisys is already recording; continuing.'
    }
  }
  $remote.InsertMessage([Ellisys.Platform.NetworkRemoteControl.Analyzer.MessageSeverity]::Info, 'Python demo started Ellisys HCI Injection recording')
  try {
    $remote.InsertComment('Python demo started Ellisys HCI Injection recording', '')
  } catch {
    Write-Host ('InsertComment skipped: ' + $_.Exception.Message)
  }
} finally {
  if ($null -ne $communicator) { $communicator.destroy() }
}
