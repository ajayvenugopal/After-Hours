import Foundation
import Darwin

public struct UsageService: Sendable {
    public init() {}
    public func load(provider: UsageProvider) async -> ProviderSnapshot {
        await Task.detached(priority: .utility) {
            switch provider {
            case .codex: return Self.loadCodex()
            case .claude: return Self.loadClaude()
            }
        }.value
    }
    private static func loadClaude() -> ProviderSnapshot {
        let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/TokenBar/claude-usage.json")
        guard let handle = try? FileHandle(forReadingFrom: url) else {
            return ProviderSnapshot(provider: .claude, message: "Install the Claude status-line bridge from Settings, then start Claude Code.")
        }
        defer { try? handle.close() }
        guard let data = try? handle.read(upToCount: 1_048_577), data.count <= 1_048_576 else {
            return ProviderSnapshot(provider: .claude, message: "Install the Claude status-line bridge from Settings, then start Claude Code.")
        }
        let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
        return (try? UsageParser.claude(data, fallbackDate: date)) ?? ProviderSnapshot(provider: .claude, message: "The Claude usage file is unreadable. Run Claude Code with the status-line bridge to update it.")
    }
    private static func loadCodex() -> ProviderSnapshot {
        if let executable = codexExecutable(), let data = try? CodexRPC.read(executable: executable), let snapshot = try? UsageParser.codexRPC(data) { return snapshot }
        if let snapshot = sessionSnapshot() { return snapshot }
        return ProviderSnapshot(provider: .codex, message: "Sign in to Codex and run a session. TokenBar reads account limits through the installed Codex app or CLI.")
    }
    private static func codexExecutable() -> URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        var paths = ["/Applications/Codex.app/Contents/Resources/codex", "\(home)/Applications/Codex.app/Contents/Resources/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex", "\(home)/.local/bin/codex", "\(home)/.npm-global/bin/codex"]
        paths += (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map { "\($0)/codex" }
        return paths.first(where: { FileManager.default.isExecutableFile(atPath: $0) }).map { URL(fileURLWithPath: $0) }
    }
    private static func sessionSnapshot() -> ProviderSnapshot? {
        let fm = FileManager.default
        let root = ProcessInfo.processInfo.environment["CODEX_HOME"].map { URL(fileURLWithPath: $0) } ?? fm.homeDirectoryForCurrentUser.appendingPathComponent(".codex")
        guard let enumerator = fm.enumerator(at: root.appendingPathComponent("sessions"), includingPropertiesForKeys: [.contentModificationDateKey, .isRegularFileKey], options: [.skipsHiddenFiles]) else { return nil }
        var files: [(URL, Date)] = []
        // Bound work even for very large installations; newest directory names first
        // are not guaranteed by FileManager, so prefer modification dates here.
        var scanned = 0
        for case let url as URL in enumerator {
            scanned += 1; if scanned > 30_000 { break }
            guard url.pathExtension == "jsonl", let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .isRegularFileKey]), values.isRegularFile == true else { continue }
            files.append((url, values.contentModificationDate ?? .distantPast))
        }
        var newest: ProviderSnapshot?
        for (url, date) in files.sorted(by: { $0.1 > $1.1 }).prefix(12) {
            guard let handle = try? FileHandle(forReadingFrom: url) else { continue }
            defer { try? handle.close() }
            guard let size = try? handle.seekToEnd() else { continue }
            let offset = size > 524_288 ? size - 524_288 : 0
            try? handle.seek(toOffset: offset)
            guard let data = try? handle.read(upToCount: 524_288) else { continue }
            // A bounded tail can start inside a multibyte character. Discard its
            // partial first record and decode each remaining record independently.
            let completeData: Data
            if offset > 0, let newline = data.firstIndex(of: 10) { completeData = Data(data.suffix(from: data.index(after: newline))) }
            else if offset > 0 { continue }
            else { completeData = data }
            let text = String(decoding: completeData, as: UTF8.self)
            let lines = text.split(separator: "\n", omittingEmptySubsequences: true)
            for line in lines.reversed() {
                guard line.contains("token_count"), let snapshot = try? UsageParser.codexSession(Data(line.utf8), fallbackDate: date) else { continue }
                if newest == nil || (snapshot.updatedAt ?? .distantPast) > (newest?.updatedAt ?? .distantPast) { newest = snapshot }
                break
            }
        }
        return newest
    }
}

/// A short-lived official app-server transport. No credential files are opened.
enum CodexRPC {
    final class Buffer: @unchecked Sendable {
        private let lock = NSLock()
        private var bytes = Data()
        private var accepting = true
        func receive(from descriptor: Int32) {
            lock.lock(); defer { lock.unlock() }
            guard accepting, bytes.count < 2_097_152 else { return }
            var chunk = [UInt8](repeating: 0, count: 65_536)
            let count = chunk.withUnsafeMutableBytes { Darwin.read(descriptor, $0.baseAddress, $0.count) }
            if count > 0 { bytes.append(contentsOf: chunk.prefix(count)) }
        }
        func stop() { lock.lock(); accepting = false; lock.unlock() }
        func messages() -> [[String: Any]] {
            lock.lock(); let copy = bytes; lock.unlock()
            return copy.split(separator: 10).compactMap { (try? JSONSerialization.jsonObject(with: Data($0))) as? [String: Any] }
        }
    }
    enum Failure: Error { case timeout, server }
    static func read(executable: URL) throws -> Data {
        let process = Process(); process.executableURL = executable; process.arguments = ["app-server"]
        let input = Pipe(); let output = Pipe(); let buffer = Buffer()
        // An exiting helper must produce a recoverable write error, not terminate TokenBar.
        guard fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1) != -1 else { throw Failure.server }
        let descriptor = output.fileHandleForReading.fileDescriptor
        let flags = fcntl(descriptor, F_GETFL)
        guard flags != -1, fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) != -1 else { throw Failure.server }
        process.standardInput = input; process.standardOutput = output; process.standardError = FileHandle.nullDevice
        output.fileHandleForReading.readabilityHandler = { _ in
            // Read only the bytes currently available; a live RPC server keeps its pipe open.
            buffer.receive(from: descriptor)
        }
        try process.run()
        defer {
            buffer.stop()
            output.fileHandleForReading.readabilityHandler = nil
            try? input.fileHandleForWriting.close()
            if process.isRunning { process.terminate() }
            // A hung server must not leave orphan processes behind.
            for _ in 0..<10 where process.isRunning { Thread.sleep(forTimeInterval: 0.02) }
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            try? output.fileHandleForReading.close()
        }
        func send(_ object: [String: Any]) throws {
            guard process.isRunning else { throw Failure.server }
            var bytes = try JSONSerialization.data(withJSONObject: object); bytes.append(10)
            try input.fileHandleForWriting.write(contentsOf: bytes)
        }
        try send(["id": 1, "method": "initialize", "params": ["clientInfo": ["name": "tokenbar", "title": "TokenBar", "version": "1.0.0"]]])
        let deadline = Date().addingTimeInterval(8)
        var requested = false
        while Date() < deadline {
            let messages = buffer.messages()
            if !requested, let initialized = messages.first(where: { ($0["id"] as? Int) == 1 }) {
                guard initialized["error"] == nil else { throw Failure.server }
                try send(["method": "initialized", "params": [:]])
                try send(["id": 2, "method": "account/rateLimits/read", "params": [:]])
                requested = true
            }
            if let response = messages.first(where: { ($0["id"] as? Int) == 2 }) {
                guard response["error"] == nil else { throw Failure.server }
                return try JSONSerialization.data(withJSONObject: response)
            }
            if !process.isRunning { throw Failure.server }
            Thread.sleep(forTimeInterval: 0.05)
        }
        throw Failure.timeout
    }
}
