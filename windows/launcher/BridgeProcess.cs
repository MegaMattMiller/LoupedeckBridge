// The Python bridge as a child process: its two pipes, its output, and stopping it. The Mac app's BridgeProcess.swift.
//
// Windows has no SIGTERM, so the bridge gets a control pipe (LB_CONTROL_HANDLE): "stop" stops it cleanly (it lets go
// of held keys and closes its ports), and if this app dies, the pipe's end stops it too. Status lines come back on
// LB_STATUS_HANDLE (bridge/status.py). Its stdout and stderr go to bridge.log, so a crash before logging starts is
// still recorded; LB_STDERR_IS_LOG tells it not to copy its log to stderr as well.

using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;

namespace LoupedeckBridge
{
    sealed class BridgeProcess
    {
        public event Action<BridgeStatus> StatusReceived;     // on a worker thread
        public event Action<int> Exited;                      // on a worker thread, once

        Process process;
        int pid;
        DateTime started;
        AnonymousPipeServerStream statusPipe;
        AnonymousPipeServerStream controlPipe;
        Timer killTimer;
        int exitReported;

        public bool Running { get; private set; }

        /// Starts `<python> -E -s -B -X utf8 -m bridge …`; false if it couldn't start (the reason is logged).
        public bool Start(RuntimePaths paths, string[] arguments)
        {
            statusPipe = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
            controlPipe = new AnonymousPipeServerStream(PipeDirection.Out, HandleInheritability.Inheritable);
            var start = new ProcessStartInfo(paths.Python)
            {
                Arguments = CommandLine.Join(BridgeCommand.Arguments(arguments)),
                WorkingDirectory = paths.Workdir,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            start.EnvironmentVariables["LB_STATUS_HANDLE"] = statusPipe.GetClientHandleAsString();
            start.EnvironmentVariables["LB_CONTROL_HANDLE"] = controlPipe.GetClientHandleAsString();
            start.EnvironmentVariables["LB_STDERR_IS_LOG"] = "1";
            try
            {
                process = Process.Start(start);
            }
            catch (Exception e) when (e is Win32Exception || e is InvalidOperationException || e is FileNotFoundException)
            {
                Log.Write($"couldn't start {paths.Python}: {e.Message}", "ERROR");
                statusPipe.Dispose();
                controlPipe.Dispose();
                return false;
            }
            // Only the bridge holds the other ends now: when it exits, the status pipe ends; when this app exits,
            // the control pipe does.
            pid = process.Id;
            started = process.StartTime;
            statusPipe.DisposeLocalCopyOfClientHandle();
            controlPipe.DisposeLocalCopyOfClientHandle();
            process.OutputDataReceived += (_, e) => { if (e.Data != null) Log.Append(e.Data + Environment.NewLine); };
            process.ErrorDataReceived += (_, e) => { if (e.Data != null) Log.Append(e.Data + Environment.NewLine); };
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.EnableRaisingEvents = true;
            process.Exited += (_, __) => ReportExit();
            Running = true;
            new Thread(ReadStatus) { IsBackground = true, Name = "bridge status" }.Start();
            if (process.HasExited) ReportExit();           // it may have exited before Exited was hooked up
            return true;
        }

        void ReadStatus()
        {
            try
            {
                using (var reader = new StreamReader(statusPipe, new UTF8Encoding(false)))
                {
                    string line;
                    while ((line = reader.ReadLine()) != null)
                    {
                        var status = BridgeStatus.Parse(line);
                        if (status != null) StatusReceived?.Invoke(status);
                    }
                }
            }
            catch (Exception e) when (e is IOException || e is ObjectDisposedException) { }
        }

        void ReportExit()
        {
            if (Interlocked.Exchange(ref exitReported, 1) == 1) return;
            process.WaitForExit();                         // lets the output readers finish
            var code = process.ExitCode;
            // A venv launcher that exited (or was ended) on its own may leave the real Python running: end it, so a
            // stopped bridge never holds the Loupedeck or the single-instance lock (ProcessTree.cs).
            ProcessTree.EndOrphans(pid, started, ProcessTree.IsPython);
            Running = false;
            killTimer?.Dispose();
            try { controlPipe.Dispose(); } catch (IOException) { }
            Exited?.Invoke(code);
        }

        /// "stop" on the control pipe: the bridge lets go of held keys and closes cleanly. Killed if it's still
        /// there after 5 s (the supervisor then lets go of the keys itself).
        public void Stop()
        {
            if (!Running) return;
            try
            {
                var stop = Encoding.UTF8.GetBytes("stop\n");
                controlPipe.Write(stop, 0, stop.Length);
                controlPipe.Flush();
            }
            catch (Exception e) when (e is IOException || e is ObjectDisposedException) { }
            var child = process;
            killTimer = new Timer(_ =>
            {
                try
                {
                    if (child.HasExited) return;
                    Log.Write("the bridge didn't stop within 5 s; forcing it", "WARNING");
                    ProcessTree.Kill(child, ProcessTree.IsPython);   // a venv launcher and its real Python
                }
                catch (Exception e) when (e is InvalidOperationException || e is Win32Exception) { }
            }, null, 5000, Timeout.Infinite);
        }
    }
}
