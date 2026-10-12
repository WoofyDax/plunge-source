# Dev helper: screenshot the Plunge window to a PNG.  usage: .\tools\shot.ps1 out.png
param([string]$Out = "shot.png")
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class PW { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
 public struct R { public int L, T, Rt, B; } }
"@
$w = Get-Process | Where-Object { $_.MainWindowTitle -eq "Plunge" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $w) { Write-Error "no Plunge window"; exit 1 }
$r = New-Object PW+R
[PW]::GetWindowRect($w.MainWindowHandle, [ref]$r) | Out-Null
$width = $r.Rt - $r.L; $height = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $width, $height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc(); [PW]::PrintWindow($w.MainWindowHandle, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
$bmp.Save((Join-Path (Get-Location) $Out), [System.Drawing.Imaging.ImageFormat]::Png)
"saved $Out ${width}x${height}"
