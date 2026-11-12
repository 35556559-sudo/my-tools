using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace LightSandbox {
  // 窗口子类化方案：替换 RDP 输入宿主窗口（IHWindowClass）的消息处理过程，
  // 在系统底层拦截 F11，不受 ActiveX 吞键影响（低级键盘钩子在本精简系统失效）。
  public class FullScreenController : IDisposable {
    private IntPtr handle = IntPtr.Zero;
    private IntPtr originalProc = IntPtr.Zero;
    private WndProcDelegate newProc;
    private Form form;
    private Control bar;
    private bool isFull = false;

    private const int GWL_WNDPROC = -4;
    private const int WM_KEYDOWN = 0x0100;
    private const int WM_SYSKEYDOWN = 0x0104;
    private const int VK_F11 = 0x7A;

    delegate IntPtr WndProcDelegate(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    delegate bool EnumChildProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr h, EnumChildProc cb, IntPtr p);
    [DllImport("user32.dll")] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr h, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] static extern IntPtr SetWindowLongPtr(IntPtr h, int index, IntPtr newProc);
    [DllImport("user32.dll")] static extern IntPtr CallWindowProc(IntPtr prev, IntPtr h, uint msg, IntPtr w, IntPtr l);

    public void Start(Form targetForm, Control statusBar) {
      form = targetForm;
      bar = statusBar;
      // 找到 RDP 输入宿主窗口 IHWindowClass
      EnumChildWindows(form.Handle, (h, p) => {
        var sb = new StringBuilder(256);
        GetClassName(h, sb, 256);
        if (sb.ToString().Contains("IHWindowClass")) { handle = h; return false; }
        return true;
      }, IntPtr.Zero);

      if (handle == IntPtr.Zero) return;
      newProc = HookedProc; // 保持委托引用，防止 GC
      IntPtr ptr = Marshal.GetFunctionPointerForDelegate(newProc);
      originalProc = GetWindowLongPtr(handle, GWL_WNDPROC);
      SetWindowLongPtr(handle, GWL_WNDPROC, ptr);
    }

    private IntPtr HookedProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam) {
      if ((msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN) && wParam == (IntPtr)VK_F11) {
        // 异步执行切换：当前正处于窗口过程中，直接改 WindowState/FormBorderStyle 会重入，
        // BeginInvoke 把切换投递到 UI 线程队列，等本次消息处理完后再执行
        form.BeginInvoke(new Action(Toggle));
        return IntPtr.Zero; // 吞掉 F11，不传给远程桌面
      }
      return CallWindowProc(originalProc, hWnd, msg, wParam, lParam);
    }

    private void Toggle() {
      isFull = !isFull;
      if (isFull) {
        form.WindowState = FormWindowState.Normal;
        form.FormBorderStyle = FormBorderStyle.None;
        if (bar != null) bar.Visible = false;
        form.WindowState = FormWindowState.Maximized;
      } else {
        form.WindowState = FormWindowState.Normal;
        form.FormBorderStyle = FormBorderStyle.Sizable;
        if (bar != null) bar.Visible = true;
      }
    }

    public void Dispose() {
      if (handle != IntPtr.Zero && originalProc != IntPtr.Zero) {
        SetWindowLongPtr(handle, GWL_WNDPROC, originalProc);
        handle = IntPtr.Zero;
        originalProc = IntPtr.Zero;
      }
    }
  }
}
