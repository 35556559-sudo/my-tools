# 轻沙箱（类虚拟机）RDP 客户端（不依赖 mstsc.exe，直接用系统 mstscax.dll 控件）
# 由主程序通过 -UserName/-Password 参数传入沙箱账户，在独立窗口显示完整沙箱桌面
param(
    [string]$Server = "127.0.0.2",
    [string]$UserName = "",
    [string]$Password = "",
    [int]$Port = 3389,
    [int]$Width = 1280,
    [int]$Height = 820
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
# 加载预编译的 AxHost 包装类（RdpHost.dll，已用 csc 编译，避开 Add-Type 编译冲突）
$dllPath = Join-Path $PSScriptRoot "RdpHost.dll"
if (-not (Test-Path $dllPath)) { $dllPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "RdpHost.dll" }
Add-Type -Path $dllPath
# 加载全屏控制器（低级键盘钩子，解决 RDP 内部窗口吞掉 F11 的问题）
$fsDll = Join-Path $PSScriptRoot "FullScreenController.dll"
if (-not (Test-Path $fsDll)) { $fsDll = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "FullScreenController.dll" }
Add-Type -Path $fsDll

# 强制窗口显示：当经 VBS 隐藏启动（SW_HIDE）时，WinForms 会继承隐藏状态，
# 用 Win32 ShowWindow 在窗口句柄创建后强制显示，避免窗口被一并隐藏
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Show {
  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

# MsTscAx.1 的 CLSID
$clsid = "{a41a4187-5a86-4e26-b40a-856f9035d9cb}"

# 主窗体
$form = New-Object System.Windows.Forms.Form
$form.Text = "沙箱桌面版（$UserName）"
$form.Size = New-Object System.Drawing.Size($Width, $Height)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)
# 可拖拽调整大小（Sizable 边框，带最大化/最小化按钮），并限制最小尺寸防止缩没
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::Sizable
$form.MinimumSize = New-Object System.Drawing.Size(820, 520)
# 允许窗体先接收键盘事件，用于 F11 全屏切换
$form.KeyPreview = $true

# 句柄一创建就强制正常显示（SW_SHOWNORMAL=1），覆盖 VBS 隐藏启动的 SW_HIDE 状态
$form.Add_HandleCreated({
  [void][Win32Show]::ShowWindow($form.Handle, 1)
})

# 顶部状态栏
$bar = New-Object System.Windows.Forms.Panel
$bar.Height = 30
$bar.Dock = "Top"
$bar.BackColor = [System.Drawing.Color]::FromArgb(240,244,248)
$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = " 正在连接 $Server`:$Port （$UserName）..."
$lbl.Dock = "Fill"
$lbl.TextAlign = "MiddleLeft"
$lbl.ForeColor = [System.Drawing.Color]::FromArgb(0,90,158)
$bar.Controls.Add($lbl)
# 右侧提示：F11 切换全屏
$tip = New-Object System.Windows.Forms.Label
$tip.Text = "F11 全屏    "
$tip.Dock = "Right"
$tip.TextAlign = "MiddleRight"
$tip.ForeColor = [System.Drawing.Color]::FromArgb(90,90,90)
$bar.Controls.Add($tip)
$form.Controls.Add($bar)

# 舞台容器：填满状态栏以下区域，黑色背景，作为等比缩放的"画布"
# RDP 控件不 Dock=Fill，而是在这个容器内始终保持 16:9 居中，多余区域留黑边，绝不拉伸变形
$stage = New-Object System.Windows.Forms.Panel
$stage.Dock = "Fill"
$stage.BackColor = [System.Drawing.Color]::Black
$form.Controls.Add($stage)

# RDP 控件（放进舞台容器，基线测试：先 Dock=Fill 确认连接渲染正常）
$host2 = New-Object LightSandbox.RdpHost($clsid)
$host2.Dock = "Fill"
$stage.Controls.Add($host2)

# 远程桌面固定 16:9（1920x1080），控件物理尺寸也始终保持 16:9，比例一致就不会变形
$script:targetRatio = 1920.0 / 1080.0
$UpdateLayout = {
    if ($stage.Width -le 0 -or $stage.Height -le 0) { return }
    $availW = [double]$stage.Width
    $availH = [double]$stage.Height
    # contain 算法：取能放进可用区域的最大 16:9 矩形
    if (($availW / $availH) -gt $script:targetRatio) {
        # 容器更宽：以高度为准，左右留黑边
        $h = $availH
        $w = $h * $script:targetRatio
    } else {
        # 容器更高：以宽度为准，上下留黑边
        $w = $availW
        $h = $w / $script:targetRatio
    }
    $x = [int](($availW - $w) / 2)
    $y = [int](($availH - $h) / 2)
    $host2.Bounds = New-Object System.Drawing.Rectangle($x, $y, [int]$w, [int]$h)
}
# Resize 注册推迟到连接建立后（见 Shown），避免在 ActiveX 初始化阶段手动改尺寸导致白屏

# 全局保存 client 引用
$script:client = $null
# 全屏控制器（低级键盘钩子，在 Shown 里句柄就绪后启动）
$fsController = New-Object LightSandbox.FullScreenController

$form.Add_Shown({
    try {
        [void][Win32Show]::ShowWindow($form.Handle, 1)
        $script:client = $host2.GetOcx()
        $script:client.Server = $Server
        if ($Port -ne 3389) { $script:client.AdvancedSettings.RDPPort = $Port }
        $script:client.UserName = $UserName
        $script:client.Domain = ""
        # 远程桌面用固定的高分辨率（独立于窗口大小），取主屏幕全屏尺寸，
        # 这样 F11 全屏时正好 1:1 填满，窗口缩小时由 SmartSizing 等比缩小
        $script:client.DesktopWidth = 1920
        $script:client.DesktopHeight = 1080
        $script:client.ColorDepth = 32
        # 凭据（本地回环，关闭 CredSSP/NLA，用标准 RDP 安全层）
        $script:client.AdvancedSettings.ClearTextPassword = $Password
        $script:client.AdvancedSettings.AuthenticationLevel = 0
        $script:client.AdvancedSettings.EnableCredSspSupport = $false
        # 重定向（剪贴板共享、不映射磁盘）
        $script:client.AdvancedSettings.RedirectClipboard = $true
        $script:client.AdvancedSettings.RedirectDrives = $false
        # 智能缩放：远程桌面像图片一样等比填满控件，窗口拖拽/最大化时内容实时缩放，不重连
        $script:client.AdvancedSettings.SmartSizing = $true
        # 连接（异步，错误通过事件返回）
        $script:client.Connect()
        $lbl.Text = " 连接请求已发出，正在建立 $UserName 沙箱桌面..."
        # 等待 RDP 输入宿主窗口 IHWindowClass 创建后再子类化（它在连接发起后才出现）
        Start-Sleep -Seconds 2
        $fsController.Start($form, $bar)
        # 连接已建立、首帧已在 Dock=Fill 下渲染，此时再切换到手动 16:9 等比布局：
        # 先关闭 Dock，再注册 Resize，然后立即做一次布局
        $host2.Dock = [System.Windows.Forms.DockStyle]::None
        $stage.Add_Resize({ & $UpdateLayout })
        & $UpdateLayout
    } catch {
        $lbl.Text = " 连接失败（同步）：" + $_.Exception.Message
    }
})

# 关闭窗体时断开
$form.Add_FormClosing({
    try {
        if ($script:client -and $script:client.Connected -ne 0) {
            $script:client.Disconnect()
        }
    } catch {}
    try { $fsController.Dispose() } catch {}
})

[void]$form.ShowDialog()
