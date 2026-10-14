import AppKit
import Foundation
import UserNotifications
import UsageCore

struct ResetNotice: Codable {
    let provider: String
    let window: String
    let remaining: Int
    let date: Date
}

@MainActor final class InsightsController: ObservableObject {
    static let directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/TokenBar")
    @Published var events: [UsageEvent] = []
    @Published var observations: [QuotaObservation] = []
    @Published var servers: [LocalServer] = []
    @Published var pace: [String: PaceEstimate] = [:]
    @Published var error: String?
    @Published var helpers: Set<String> = []
    @Published var notifications = UserDefaults.standard.bool(forKey: "notifications")
    @Published var resetNotifications = UserDefaults.standard.object(forKey: "resetNotifications") as? Bool ?? true {
        didSet { UserDefaults.standard.set(resetNotifications, forKey: "resetNotifications") }
    }
    @Published var lastReset: ResetNotice?
    @Published var localEnabled = UserDefaults.standard.object(forKey: "localEnabled") as? Bool ?? true {
        didSet { UserDefaults.standard.set(localEnabled, forKey: "localEnabled") }
    }
    @Published var threshold = UserDefaults.standard.object(forKey: "lowThreshold") as? Double ?? 20 {
        didSet { UserDefaults.standard.set(threshold, forKey: "lowThreshold") }
    }
    @Published var budget = UserDefaults.standard.double(forKey: "monthlyBudget") {
        didSet { UserDefaults.standard.set(budget, forKey: "monthlyBudget") }
    }
    private var processes: [String: Process] = [:]
    private let demo: Bool
    private let nativeSessions = NativeSessionEvents()
    private var lastActivityRefresh = Date.distantPast
    init(demo: Bool = false) {
        self.demo = demo
        if !demo, let saved = UserDefaults.standard.data(forKey: "lastQuotaReset") {
            lastReset = try? JSONDecoder().decode(ResetNotice.self, from: saved)
        }
        if !demo && UserDefaults.standard.object(forKey: "resetNotifications") == nil {
            UserDefaults.standard.set(true, forKey: "resetNotifications")
            enableNotifications(true)
        }
    }
    var todayEvents: [UsageEvent] { events.filter { Calendar.current.isDateInToday($0.timestamp) } }
    var monthEvents: [UsageEvent] {
        let interval = Calendar.current.dateInterval(of: .month, for: Date())!
        return events.filter { interval.contains($0.timestamp) }
    }
    var monthCost: Double { monthEvents.compactMap(\.estimatedCostUSD).reduce(0, +) }
    var measuredCostCount: Int { monthEvents.filter { $0.estimatedCostUSD != nil }.count }
    var providerNames: [String] { Array(Set(events.map(\.provider))).sorted() }
    func refresh(snapshots: [ProviderSnapshot]) async {
        guard !demo else { return }
        let directory = Self.directory
        let points = snapshots.flatMap { snapshot in
            snapshot.windows.compactMap { window -> QuotaObservation? in
                guard let date = snapshot.updatedAt else { return nil }
                return QuotaObservation(provider: snapshot.provider.rawValue, windowID: window.id, date: date, usedPercent: window.usedPercent, resetsAt: window.resetsAt)
            }
        }
        let limit = threshold
        let alertPoints = points.filter { Date().timeIntervalSince($0.date) >= -60 && Date().timeIntervalSince($0.date) <= 900 }
        let updateActivity = Date().timeIntervalSince(lastActivityRefresh) >= 120
        do {
            let nativeEvents = updateActivity ? await nativeSessions.load() : []
            let data: ([QuotaObservation], [String: PaceEstimate], [UsageEvent], [QuotaAlert]) = try await Task.detached(priority: .utility) {
                let alerts = try AlertEngine(url: directory.appendingPathComponent("alert-state.json")).evaluate(alertPoints, lowRemainingThreshold: limit)
                guard updateActivity else { return ([], [:], [], alerts) }
                let history = HistoryLedger(url: directory.appendingPathComponent("quota-history.json"))
                try history.record(points)
                let records = try history.observations()
                var rates: [String: PaceEstimate] = [:]
                for point in points {
                    if let rate = HistoryLedger.pace(in: records, provider: point.provider, windowID: point.windowID) { rates[point.provider + ":" + point.windowID] = rate }
                }
                let ledger = EventLedger(url: directory.appendingPathComponent("events.jsonl"))
                try ledger.append(nativeEvents)
                let events = try ledger.events()
                return (records, rates, events, alerts)
            }.value
            if updateActivity {
                observations = data.0; pace = data.1; events = data.2
                lastActivityRefresh = Date()
            }
            for alert in data.3 {
                let reset = alert.kind == .reset
                let snapshot = snapshots.first { $0.provider.rawValue == alert.provider }
                let provider = snapshot?.provider.title ?? alert.provider.capitalized
                let window = snapshot?.windows.first { $0.id == alert.windowID }?.title ?? alert.windowID
                let remaining = Int(alert.remainingPercent.rounded())
                if reset {
                    let receipt = ResetNotice(provider: provider, window: window, remaining: remaining, date: Date())
                    lastReset = receipt
                    if let encoded = try? JSONEncoder().encode(receipt) { UserDefaults.standard.set(encoded, forKey: "lastQuotaReset") }
                }
                if notifications && (!reset || resetNotifications) {
                    notify(id: UUID().uuidString,
                           title: reset ? "\(provider) quota reset" : "\(provider) quota running low",
                           body: "\(window): \(remaining)% remaining." + (reset ? " Your allowance is available again." : ""))
                }
            }
            if notifications {
                let month = Date().formatted(.dateTime.year().month())
                if budget > 0, monthCost >= budget, UserDefaults.standard.string(forKey: "budgetAlertMonth") != month {
                    notify(id: "budget-" + month, title: "Monthly budget reached", body: "Recorded costs reached your $\(Int(budget)) budget. Some activity may not include cost data.")
                    UserDefaults.standard.set(month, forKey: "budgetAlertMonth")
                }
            }
            error = nil
        } catch { self.error = "Could not read usage history: \(error.localizedDescription)" }
        if localEnabled && updateActivity {
            async let ollama = LocalModels.load(id: "ollama")
            async let lmstudio = LocalModels.load(id: "lmstudio")
            servers = await [ollama, lmstudio]
        } else if !localEnabled { servers = [] }
    }
    func enableNotifications(_ enabled: Bool) {
        if !enabled { notifications = false; UserDefaults.standard.set(false, forKey: "notifications"); return }
        Task {
            do {
                notifications = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
                UserDefaults.standard.set(notifications, forKey: "notifications")
                if !notifications { error = "Notifications are disabled in macOS System Settings." }
            } catch { self.error = error.localizedDescription }
        }
    }
    private func notify(id: String, title: String, body: String) {
        let content = UNMutableNotificationContent(); content.title = title; content.body = body
        content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
    }
    func startHelper(_ id: String) {
        guard processes[id] == nil else { return }
        let script = id == "gemini" ? "gemini-telemetry.py" : "capture-usage.py"
        guard let resource = Bundle.main.resourceURL?.appendingPathComponent(script), FileManager.default.fileExists(atPath: resource.path) else { error = "Build the app bundle to use connection helpers."; return }
        let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        guard let python = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { error = "Install Python 3 to use connection helpers."; return }
        let process = Process(); process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [resource.path] + (id == "gemini" ? [] : ["--provider", id])
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { [weak self] process in
            Task { @MainActor in
                self?.processes.removeValue(forKey: id); self?.helpers.remove(id)
                if process.terminationStatus != 0 { self?.error = "\(id.capitalized) helper stopped. Its port may already be in use; see the connection guide." }
            }
        }
        do { try process.run(); processes[id] = process; helpers.insert(id) }
        catch { self.error = error.localizedDescription }
    }
    func stopHelper(_ id: String) { processes[id]?.terminate() }
    func shutdown() { for process in processes.values where process.isRunning { process.terminate() } }
    func openGuide() {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("INTEGRATIONS.md") else { return }
        NSWorkspace.shared.open(url)
    }
    func exportCSV() {
        let panel = NSSavePanel(); panel.nameFieldStringValue = "tokenbar-usage.csv"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { try EventLedger(url: Self.directory.appendingPathComponent("events.jsonl")).csv().write(to: url, atomically: true, encoding: .utf8) }
        catch { self.error = error.localizedDescription }
    }
    func importEvents() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task {
            do {
                let loaded = try await Task.detached {
                    try EventLedger(url: url).events()
                }.value
                guard !loaded.isEmpty else { error = "No valid events found. Use the JSONL event format in the connection guide."; return }
                try EventLedger(url: Self.directory.appendingPathComponent("events.jsonl")).append(loaded)
                events = try EventLedger(url: Self.directory.appendingPathComponent("events.jsonl")).events()
                error = nil
            } catch { self.error = error.localizedDescription }
        }
    }
}
