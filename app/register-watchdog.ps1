# ウォッチドッグをタスクスケジューラに登録する。初回設定から呼ばれる。
# ノート PC でバッテリー稼働中も動かす必要があるため XML 定義で登録する。

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$vbs  = Join-Path $root 'watchdog.vbs'

# タスク名は据え置く。名前を変えると schtasks /F の上書きが効かず、
# 前の版で登録した「PauseTask Watchdog」が消せないまま残り続ける。
$name    = 'PauseTask Watchdog'
$xmlPath = Join-Path $env:TEMP 'pausetask-watchdog.xml'

if (-not (Test-Path $vbs)) {
    Write-Output "watchdog.vbs が見つかりません: $vbs"
    exit 1
}

# UserId を明示しないと「全ユーザーのログオン」扱いになり管理者権限を要求される
$me = "$env:USERDOMAIN\$env:USERNAME"

# パスやユーザー名に & < > " が混ざっても壊れないようエスケープしてから XML に埋める
$vbsXml = [System.Security.SecurityElement]::Escape($vbs)
$meXml  = [System.Security.SecurityElement]::Escape($me)

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Click Up Widget の常駐が落ちていたら再起動する</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT2M</Delay>
      <UserId>$meXml</UserId>
    </LogonTrigger>
    <TimeTrigger>
      <StartBoundary>2026-01-01T00:03:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$meXml</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$vbsXml"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$xml | Out-File -FilePath $xmlPath -Encoding unicode
try {
    schtasks /Create /TN $name /XML $xmlPath /F 2>&1 | Out-Null

    if ($LASTEXITCODE -eq 0) {
        Write-Output "タスク「$name」を登録しました。"
        Write-Output '5 分ごとに常駐を確認し、落ちていれば自動で起動し直します。'
    } else {
        # XML 登録が拒否された環境向けのフォールバック。
        # バッテリー稼働時に動かない制約が残るため、その旨を伝える。
        #
        # \`" の \ は消さないこと。Windows PowerShell 5.1 はネイティブ exe に引数を渡すとき
        # 引用符を落とすため、\" と書かないと schtasks に "パス" が渡らない。
        # 実測: \`" あり → wscript.exe "C:\...\watchdog.vbs" ／ なし → 引用符が消える
        schtasks /Create /TN $name /TR "wscript.exe \`"$vbs\`"" /SC MINUTE /MO 5 /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "タスクの登録に失敗しました (exit $LASTEXITCODE)" }
        Write-Output "タスク「$name」を簡易設定で登録しました。"
        Write-Output '※ バッテリー稼働中は動作しません。常時動かすには タスクスケジューラ で'
        Write-Output '  「電源」タブの「コンピューターをバッテリで実行している場合は開始しない」を外してください。'
    }
} finally {
    Remove-Item $xmlPath -Force -ErrorAction SilentlyContinue
}
