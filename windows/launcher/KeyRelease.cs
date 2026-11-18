// After the bridge ended without its own clean-up (killed when a stop timed out, or crashed): let go of every key it
// could hold. Harmless when nothing was held. The Mac app's BridgeProcess.releaseKeys().

using System;
using System.Runtime.InteropServices;

namespace LoupedeckBridge
{
    static class KeyRelease
    {
        /// Every key the bridge can hold down: Shift, Ctrl, Alt, Tab and the four arrows. The same list as
        /// bridge/platform/windows_keys.py HOLDABLE_VKS (tests/test_windows_tray_keys.py keeps them in step).
        public static readonly ushort[] HoldableKeys = { 0x10, 0x11, 0x12, 0x09, 0x25, 0x26, 0x27, 0x28 };

        const ushort Alt = 0x12;
        const ushort MenuMask = 0xE8;          // unassigned: before Alt's release, so a menu bar doesn't take focus
        const uint InputKeyboard = 1;
        const uint ExtendedKey = 0x0001;
        const uint KeyUp = 0x0002;

        public static void ReleaseAll()
        {
            foreach (var vk in HoldableKeys)
            {
                if (vk == Alt)
                {
                    Send(MenuMask, down: true);
                    Send(MenuMask, down: false);
                }
                Send(vk, down: false);
            }
        }

        static void Send(ushort vk, bool down)
        {
            var extended = vk >= 0x25 && vk <= 0x28;
            var input = new INPUT
            {
                type = InputKeyboard,
                ki = new KEYBDINPUT
                {
                    wVk = vk, wScan = (ushort)MapVirtualKey(vk, 0), dwFlags = (extended ? ExtendedKey : 0) | (down ? 0 : KeyUp),
                },
            };
            SendInput(1, new[] { input }, Marshal.SizeOf(typeof(INPUT)));
        }

        [StructLayout(LayoutKind.Sequential)]
        struct KEYBDINPUT
        {
            public ushort wVk;
            public ushort wScan;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        // INPUT's union is as big as MOUSEINPUT; the padding gives it Windows' size (40 bytes on 64-bit).
        [StructLayout(LayoutKind.Sequential)]
        struct INPUT
        {
            public uint type;
            public KEYBDINPUT ki;
            public long padding;
        }

        [DllImport("user32.dll", SetLastError = true)]
        static extern uint SendInput(uint count, INPUT[] inputs, int size);

        [DllImport("user32.dll")]
        static extern uint MapVirtualKey(uint code, uint mapType);
    }
}
