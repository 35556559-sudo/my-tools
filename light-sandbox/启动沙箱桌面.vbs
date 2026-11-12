Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "F:\项目\隔离沙箱"
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""F:\项目\隔离沙箱\沙箱桌面客户端.ps1""", 0, False