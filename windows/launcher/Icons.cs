// The tray icons, drawn in code (no image files): sliders when all is well, a warning triangle otherwise, and the
// coloured dots for the menu's status lines. The sliders follow the taskbar's theme (light or dark).

using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

namespace LoupedeckBridge
{
    static class Icons
    {
        public static Icon Good { get; } = Make(DrawSliders);
        public static Icon Attention { get; } = Make(DrawWarning);
        public static Image GreenDot { get; } = Dot(Color.FromArgb(0x2E, 0xA0, 0x43));
        public static Image OrangeDot { get; } = Dot(Color.FromArgb(0xE8, 0x8A, 0x00));

        static Icon Make(Action<Graphics, int> draw)
        {
            var size = Math.Max(16, SystemInformation.SmallIconSize.Width);
            using (var bitmap = new Bitmap(size, size))
            {
                using (var g = Graphics.FromImage(bitmap))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.Clear(Color.Transparent);
                    draw(g, size);
                }
                var handle = bitmap.GetHicon();
                try { return (Icon)Icon.FromHandle(handle).Clone(); }
                finally { DestroyIcon(handle); }
            }
        }

        static bool LightTaskbar()
        {
            using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"))
                return key?.GetValue("SystemUsesLightTheme") is int light && light == 1;
        }

        static void DrawSliders(Graphics g, int size)
        {
            var ink = LightTaskbar() ? Color.FromArgb(0x20, 0x20, 0x20) : Color.White;
            float unit = size / 16f;
            using (var line = new Pen(ink, 1.5f * unit))
            using (var knob = new SolidBrush(ink))
            {
                float[] rows = { 3.5f, 8f, 12.5f };
                float[] knobs = { 10.5f, 5f, 8.5f };
                for (var i = 0; i < 3; i++)
                {
                    g.DrawLine(line, 1.5f * unit, rows[i] * unit, 14.5f * unit, rows[i] * unit);
                    g.FillEllipse(knob, (knobs[i] - 2f) * unit, (rows[i] - 2f) * unit, 4f * unit, 4f * unit);
                }
            }
        }

        static void DrawWarning(Graphics g, int size)
        {
            float unit = size / 16f;
            var triangle = new[] { new PointF(8f * unit, 1f * unit), new PointF(15.5f * unit, 14.5f * unit),
                                   new PointF(0.5f * unit, 14.5f * unit) };
            using (var fill = new SolidBrush(Color.FromArgb(0xF2, 0xA1, 0x00))) g.FillPolygon(fill, triangle);
            using (var mark = new SolidBrush(Color.Black))
            {
                g.FillRectangle(mark, 7.1f * unit, 5f * unit, 1.8f * unit, 5f * unit);
                g.FillEllipse(mark, 7f * unit, 11.3f * unit, 2f * unit, 2f * unit);
            }
        }

        static Image Dot(Color color)
        {
            var bitmap = new Bitmap(16, 16);
            using (var g = Graphics.FromImage(bitmap))
            using (var fill = new SolidBrush(color))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.FillEllipse(fill, 4, 4, 8, 8);
            }
            return bitmap;
        }

        [DllImport("user32.dll")]
        static extern bool DestroyIcon(IntPtr handle);
    }
}
