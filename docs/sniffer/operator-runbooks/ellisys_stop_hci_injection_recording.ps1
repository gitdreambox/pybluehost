
$ErrorActionPreference = 'Stop'
[Reflection.Assembly]::LoadFrom('C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\RemoteControl\Ice.dll') | Out-Null
[Reflection.Assembly]::LoadFrom('C:\ProgramData\Ellisys\Ellisys Bluetooth Analyzer\Updates\current\RemoteControl\EllisysAnalyzerBluetoothRemoteControlPlugin.dll') | Out-Null
$communicator = [Ice.Util]::initialize()
try {
  $proxy = $communicator.stringToProxy('Ellisys.AnalyzerRemoteControl.Bluetooth:tcp -h localhost -p 46148')
  $remote = [Ellisys.Platform.NetworkRemoteControl.Analyzer.BluetoothAnalyzerRemoteControlPrxHelper]::checkedCast($proxy)
  if ($null -eq $remote) { throw 'Failed to cast Ellisys remote control proxy' }
  if ($remote.IsRecording()) {
    $remote.StopRecordingAndSaveTraceFile('H:\github\bluetooth\pybluehost\pybluehost\tools\ellisys_single_file_smoke.btt', $true)
  } else {
    Write-Host 'Ellisys was not recording at stop time'
  }
} finally {
  if ($null -ne $communicator) { $communicator.destroy() }
}
