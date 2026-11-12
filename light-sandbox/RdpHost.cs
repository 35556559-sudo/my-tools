using System;
using System.Windows.Forms;
namespace LightSandbox {
  public class RdpHost : AxHost {
    public RdpHost(string clsid) : base(clsid) { }
    public new object GetOcx() { return base.GetOcx(); }
  }
}