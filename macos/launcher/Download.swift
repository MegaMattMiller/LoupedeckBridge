// The updater's downloads (milestone 6, v0.5.1): streamed to a file, refused past a size limit, and hashed
// (SHA-256) as they arrive, so a tampered release can't fill memory or the disk before the checks run.

import CryptoKit
import Foundation

enum Download {
    struct Done {
        let file: URL
        let sha256: String          // lowercase hex
        let bytes: Int64
    }

    struct Failure: Error {
        let reason: String
    }

    /// Blocking (call it from a background queue). An https URL from a release, or a file URL in tests.
    static func fetch(_ url: URL, to file: URL, limit: Int64, userAgent: String,
                      timeout: TimeInterval = 60) throws -> Done {
        guard FileManager.default.createFile(atPath: file.path, contents: nil),
              let handle = try? FileHandle(forWritingTo: file) else {
            throw Failure(reason: "couldn't write \(file.lastPathComponent)")
        }
        defer { try? handle.close() }
        let writer = CappedWriter(limit: limit, handle: handle)
        let config = URLSessionConfiguration.ephemeral         // no cookies, no cache
        config.timeoutIntervalForRequest = timeout
        let queue = OperationQueue()
        queue.maxConcurrentOperationCount = 1
        let session = URLSession(configuration: config, delegate: writer, delegateQueue: queue)
        defer { session.finishTasksAndInvalidate() }            // a session keeps its delegate until then
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        session.dataTask(with: request).resume()
        writer.finished.wait()
        if let failure = writer.failure { throw Failure(reason: failure) }
        let digest = writer.hasher.finalize().map { String(format: "%02x", $0) }.joined()
        return Done(file: file, sha256: digest, bytes: writer.bytes)
    }

    static func size(_ bytes: Int64) -> String {
        bytes >= 1_048_576 ? "\(bytes / 1_048_576) MB" : "\(bytes) bytes"
    }
}

/// Writes what arrives to the file and hashes it, until the limit; then cancels.
private final class CappedWriter: NSObject, URLSessionDataDelegate {
    let limit: Int64
    let handle: FileHandle
    var hasher = SHA256()
    var bytes: Int64 = 0
    var failure: String?
    let finished = DispatchSemaphore(value: 0)

    init(limit: Int64, handle: FileHandle) {
        self.limit = limit
        self.handle = handle
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            failure = "GitHub answered \(http.statusCode)"
        } else if response.expectedContentLength > limit {
            failure = "it's bigger than \(Download.size(limit))"
        }
        completionHandler(failure == nil ? .allow : .cancel)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard failure == nil else { return }
        bytes += Int64(data.count)
        if bytes > limit {
            failure = "it's bigger than \(Download.size(limit))"
            dataTask.cancel()
            return
        }
        hasher.update(data: data)
        do {
            try handle.write(contentsOf: data)
        } catch {
            failure = "couldn't save it (\(error.localizedDescription))"
            dataTask.cancel()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if failure == nil, let error = error { failure = error.localizedDescription }
        finished.signal()
    }
}
