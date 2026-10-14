import AppKit
import SwiftUI
import ServiceManagement
import Combine
import UsageCore
import UserNotifications

@main
struct TokenBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene { Settings { EmptyView() } }
}

@MainActor final class UsageStore: ObservableObject {
    @Published var snapshots: [ProviderSnapshot] = []
    @Published var refreshing = false
    @Published var checkingReset: UsageProvider?
    @Published var resetChecks: [UsageProvider: ResetCheckResult] = [:]
    @Published var settingsVisible = false
    @Published var selectedTab = "Usage"
    @Published var loginEnabled = SMAppService.mainApp.status == .enabled
    @Published var loginError: String?
    @Published var codexEnabled = UserDefaults.standard.object(forKey: "codexEnabled") as? Bool ?? true {
        didSet { UserDefaults.standard.set(codexEnabled, forKey: "codexEnabled") }
    }
    @Published var claudeEnabled = UserDefaults.standard.object(forKey: "claudeEnabled") as? Bool ?? true {
        didSet { UserDefaults.standard.set(claudeEnabled, forKey: "claudeEnabled") }
    }
    var visibleSnapshots: [ProviderSnapshot] {
        snapshots.filter { snapshot in
            snapshot.provider == .codex ? codexEnabled : (claudeEnabled && !snapshot.windows.isEmpty)
        }
    }
    let insights: InsightsController
    @Published var menuStyle: String = {
        let saved = UserDefaults.standard.string(forKey: "menuStyle") ?? "full"
        let style = ["full", "quota", "icon"].contains(saved) ? saved : "full"
        UserDefaults.standard.set(style, forKey: "menuStyle")
        return style
    }() {
        didSet { UserDefaults.standard.set(menuStyle, forKey: "menuStyle") }
    }
    @Published var toolbarMode = UserDefaults.standard.string(forKey: "toolbarMode") ?? "all" {
        didSet { UserDefaults.standard.set(toolbarMode, forKey: "toolbarMode") }
    }
    @Published var preferredToolbarProvider = UserDefaults.standard.string(forKey: "preferredToolbarProvider") ?? "codex" {
        didSet { UserDefaults.standard.set(preferredToolbarProvider, forKey: "preferredToolbarProvider") }
    }
    let demo: Bool
    private var started = false
    private let service = UsageService()
    init(demo: Bool = ProcessInfo.processInfo.arguments.contains("--preview")) {
        self.demo = demo
        insights = InsightsController(demo: demo)
        if demo { snapshots = Self.examples }
        else {
            snapshots = UsageProvider.allCases.map {
                ProviderSnapshot(provider: $0, windows: [], updatedAt: nil, source: "Local usage", message: "Reading local usage…", contextRemainingTokens: nil)
            }
        }
        Task { await start() }
    }
    var availableSnapshots: [ProviderSnapshot] { visibleSnapshots.filter { !$0.windows.isEmpty } }
    func shortWindow(_ snapshot: ProviderSnapshot) -> UsageWindow? {
        snapshot.windows.first { $0.id == "primary" || $0.id == "session" }
            ?? snapshot.windows.filter { ($0.durationMinutes ?? 10080) < 10080 }.min { ($0.durationMinutes ?? 0) < ($1.durationMinutes ?? 0) }
    }
    func menuValue(_ snapshot: ProviderSnapshot) -> String {
        guard let window = shortWindow(snapshot) else { return "—" }
        let now = Date()
        let stale = snapshot.updatedAt.map { now.timeIntervalSince($0) > 900 } ?? true
        let expired = window.resetsAt.map { $0 <= now } ?? false
        let quota = stale || expired ? "?" : "\(Int(window.remainingPercent.rounded()))%"
        guard let reset = window.resetsAt else { return "\(quota) · reset —" }
        let seconds = max(0, Int(ceil(reset.timeIntervalSince(now))))
        guard seconds > 0 else { return "\(quota) · reset due" }
        let hours = seconds / 3600, minutes = seconds % 3600 / 60
        let timer = hours > 0 ? "\(hours)h \(minutes)m" : "\(minutes)m \(seconds % 60)s"
        return "\(quota) · \(timer)"
    }
    func start() async {
        guard !started else { return }; started = true
        await refresh()
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 20_000_000_000)
            if Task.isCancelled { return }
            await refresh()
        }
    }
    func refresh() async {
        guard !demo, !refreshing else { return }
        refreshing = true
        async let codex = service.load(provider: .codex)
        async let claude = service.load(provider: .claude)
        snapshots = await [codex, claude]
        await insights.refresh(snapshots: snapshots)
        refreshing = false
    }
    func setLogin(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() }
            else { try SMAppService.mainApp.unregister() }
            loginEnabled = SMAppService.mainApp.status == .enabled
            loginError = nil
        } catch { loginError = error.localizedDescription }
    }
    func checkReset(provider: UsageProvider) async {
        guard !refreshing else { return }
        refreshing = true
        checkingReset = provider
        defer { refreshing = false; checkingReset = nil }
        let previous = snapshots.first { $0.provider == provider }
        let current = demo ? (previous ?? ProviderSnapshot(provider: provider)) : await service.load(provider: provider)
        if let index = snapshots.firstIndex(where: { $0.provider == provider }) { snapshots[index] = current }
        resetChecks[provider] = ResetCheckResult.evaluate(current: current, previous: previous)
        await insights.refresh(snapshots: snapshots)
    }
    static var examples: [ProviderSnapshot] {
        [ProviderSnapshot(provider: .codex, windows: [
            UsageWindow(id: "session", title: "5-hour window", usedPercent: 28, resetsAt: Date().addingTimeInterval(8430), durationMinutes: 300),
            UsageWindow(id: "week", title: "Weekly", usedPercent: 44, resetsAt: Date().addingTimeInterval(221400), durationMinutes: 10080)
        ], updatedAt: Date().addingTimeInterval(-24), source: "Local Codex session", message: nil, contextRemainingTokens: nil),
         ProviderSnapshot(provider: .claude, windows: [
            UsageWindow(id: "session", title: "5-hour window", usedPercent: 64, resetsAt: Date().addingTimeInterval(4560), durationMinutes: 300),
            UsageWindow(id: "week", title: "Weekly", usedPercent: 19, resetsAt: Date().addingTimeInterval(389300), durationMinutes: 10080)
         ], updatedAt: Date().addingTimeInterval(-42), source: "Claude Code status line", message: nil, contextRemainingTokens: 168000)]
    }
}

private enum Brand {
    // Remove the app artwork's outer transparent margin and draw at full status-bar height.
    private static func statusIcon(_ source: NSImage?, fallback: NSImage) -> NSImage {
        guard let source else { return fallback }
        let size = source.size
        return NSImage(size: NSSize(width: 22, height: 22), flipped: false) { rect in
            source.draw(in: rect, from: NSRect(x: size.width * 0.085, y: size.height * 0.085, width: size.width * 0.83, height: size.height * 0.83), operation: .sourceOver, fraction: 1)
            return true
        }
    }
    // The standalone reference mark, without its wordmark, drawn as a Retina template.
    static let largeCodexMenu = tokenBarMenu
    static let largeClaudeMenu = tokenBarMenu
    static let genericMenu = tokenBarMenu
    private static let tokenBarMenu: NSImage = {
        let image = NSImage(size: NSSize(width: 20, height: 20), flipped: false) { _ in
            NSGraphicsContext.saveGraphicsState()
            defer { NSGraphicsContext.restoreGraphicsState() }
            let tilt = NSAffineTransform()
            tilt.translateX(by: 10, yBy: 10)
            tilt.rotate(byDegrees: 7)
            tilt.translateX(by: -10, yBy: -10)
            tilt.concat()
            let mark = NSBezierPath(roundedRect: NSRect(x: 1.5, y: 2.25, width: 17, height: 15.5), xRadius: 5, yRadius: 5)
            mark.appendOval(in: NSRect(x: 5.3, y: 8.4, width: 3.6, height: 3.6))
            mark.appendOval(in: NSRect(x: 11.1, y: 8.4, width: 3.6, height: 3.6))
            mark.windingRule = .evenOdd
            NSColor.black.setFill()
            mark.fill()
            return true
        }
        image.isTemplate = true
        return image
    }()
    static let codex: NSImage? = {
        let roots = ["/Applications/Codex.app", FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/Codex.app").path]
        for root in roots {
            if let image = NSImage(contentsOfFile: root + "/Contents/Resources/icon-codex-light.png") { return image }
        }
        return nil
    }()
    static let claude: NSImage? = {
        for path in ["/Applications/Claude.app", FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/Claude.app").path] {
            if FileManager.default.fileExists(atPath: path) { return NSWorkspace.shared.icon(forFile: path) }
        }
        return nil
    }()
    static let claudeMenu: NSImage = {
        if let source = claude {
            return NSImage(size: NSSize(width: 19, height: 19), flipped: false) { rect in source.draw(in: rect); return true }
        }
        // Claude's radial asterisk remains recognizable without the desktop app.
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
            NSColor.labelColor.setStroke()
            let path = NSBezierPath()
            path.lineWidth = 1.7
            path.lineCapStyle = .round
            for index in 0..<12 {
                let angle = Double(index) * .pi / 6
                path.move(to: NSPoint(x: 9 + cos(angle) * 2, y: 9 + sin(angle) * 2))
                path.line(to: NSPoint(x: 9 + cos(angle) * 7.5, y: 9 + sin(angle) * 7.5))
            }
            path.stroke()
            return true
        }
        image.isTemplate = true
        return image
    }()
    static let codexMenu: NSImage = {
        guard let source = codex else { return NSImage(systemSymbolName: "terminal", accessibilityDescription: "Codex")! }
        let image = NSImage(size: NSSize(width: 19, height: 19), flipped: false) { rect in
            source.draw(in: rect)
            return true
        }
        image.isTemplate = false
        return image
    }()
}

enum Palette {
    static let background = Color(nsColor: .windowBackgroundColor)
    static let card = Color(nsColor: NSColor(name: nil) { appearance in
        NSColor(calibratedWhite: appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? 0.17 : 1, alpha: 1)
    })
    static let muted = Color.secondary
    static let blue = Color(nsColor: NSColor(name: nil) { appearance in
        if appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua {
            return NSColor(calibratedRed: 0.43, green: 0.78, blue: 0.68, alpha: 1)
        }
        return NSColor(calibratedRed: 0.10, green: 0.46, blue: 0.39, alpha: 1)
    })
    static let mint = Color(red: 0.22, green: 0.62, blue: 0.43)
    static let orange = Color.orange
    static let border = Color.primary.opacity(0.08)
}

struct DashboardView: View {
    @ObservedObject var store: UsageStore
    private var settings: Bool {
        get { store.settingsVisible }
        nonmutating set { store.settingsVisible = newValue }
    }
    private var tab: String {
        get { store.selectedTab }
        nonmutating set { store.selectedTab = newValue }
    }
    @Namespace private var tabSelection
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { timeline in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        HStack(spacing: 7) {
                            Image(systemName: "chart.bar.xaxis").foregroundColor(Palette.blue)
                            Text("TokenBar").font(.system(size: 14, weight: .semibold))
                        }
                        Spacer()
                        if store.demo { Text("PREVIEW").font(.system(size: 8, weight: .bold)).foregroundColor(Palette.orange) }
                        Button { Task { await store.refresh() } } label: {
                            Image(systemName: "arrow.clockwise").rotationEffect(.degrees(store.refreshing ? 180 : 0))
                                .animation(reduceMotion ? nil : .easeInOut(duration: 0.5), value: store.refreshing).frame(width: 27, height: 27)
                        }.disabled(store.refreshing).help("Refresh usage")
                        Button { withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) { settings.toggle() } } label: {
                            Image(systemName: settings ? "xmark" : "slider.horizontal.3").frame(width: 27, height: 27)
                        }.help("Settings")
                    }.buttonStyle(.plain).foregroundColor(Palette.muted)
                    if settings { settingsView.transition(.opacity.combined(with: .move(edge: .top))) }
                    HStack(spacing: 4) {
                        ForEach(["Usage", "History", "Connect"], id: \.self) { name in
                            Button {
                                withAnimation(reduceMotion ? nil : .spring(response: 0.32, dampingFraction: 0.86)) { tab = name }
                            } label: {
                                Text(name).font(.system(size: 12, weight: .medium))
                                    .foregroundColor(tab == name ? .primary : Palette.muted)
                                    .frame(maxWidth: .infinity).padding(.vertical, 8)
                                    .background {
                                        if tab == name {
                                            RoundedRectangle(cornerRadius: 7).fill(Palette.card)
                                                .shadow(color: .black.opacity(0.07), radius: 2, y: 1)
                                                .matchedGeometryEffect(id: "tab", in: tabSelection)
                                        }
                                    }
                            }.buttonStyle(.plain).accessibilityAddTraits(tab == name ? .isSelected : [])
                        }
                    }.padding(3).background(Palette.border.opacity(0.6)).cornerRadius(10)
                    Group {
                    if tab == "Usage" {
                    ResetActivityView(insights: store.insights, now: timeline.date)
                    if store.visibleSnapshots.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("No providers connected").font(.system(size: 23, weight: .medium, design: .default))
                            Text("Enable Codex in settings, or connect Claude Code to see your usage.").font(.system(size: 12)).foregroundColor(Palette.muted)
                            Button("Manage providers") { settings = true }.buttonStyle(.plain).foregroundColor(Palette.blue)
                        }.padding(20)
                    }
                    ForEach(store.visibleSnapshots, id: \.provider) { snapshot in
                        ProviderCard(snapshot: snapshot, now: timeline.date,
                                     resetCheck: store.resetChecks[snapshot.provider],
                                     checking: store.checkingReset == snapshot.provider,
                                     checkDisabled: store.refreshing) {
                            Task { await store.checkReset(provider: snapshot.provider) }
                        }
                        PaceView(insights: store.insights, provider: snapshot.provider.rawValue)
                    }
                    LocalActivityView(insights: store.insights)
                    } else if tab == "History" {
                        HistoryView(insights: store.insights)
                    } else {
                        ConnectionsView(insights: store.insights)
                    }
                    }.id(tab).transition(.opacity)
                    Divider().overlay(Palette.border)
                    HStack(spacing: 5) {
                        Circle().fill(store.refreshing ? Palette.orange : Palette.mint).frame(width: 5, height: 5)
                        Text(store.refreshing ? "Updating usage…" : "Refreshes every 20 seconds").font(.system(size: 10))
                        Spacer()
                        Button("Quit") { NSApplication.shared.terminate(nil) }.buttonStyle(.plain).font(.system(size: 10))
                    }.foregroundColor(Palette.muted)
                }.padding(20)
            }.frame(width: 380).frame(maxHeight: 730).fixedSize(horizontal: false, vertical: true)
                .background(Palette.background)
        }.foregroundColor(.primary).tint(Palette.blue)
    }
    private var settingsView: some View {
        VStack(alignment: .leading, spacing: 13) {
            Text("PREFERENCES").font(.system(size: 9, weight: .bold)).tracking(1.5).foregroundColor(Palette.muted)
            Picker("Menu bar", selection: $store.menuStyle) {
                Text("Icon + quota + timer").tag("full")
                Text("Icon + quota").tag("quota")
                Text("Icon only").tag("icon")
            }
            Picker("Providers in menu bar", selection: $store.toolbarMode) {
                Text("Show all available").tag("all")
                Text("Show one provider").tag("one")
            }
            if store.toolbarMode == "one" {
                Picker("Default provider", selection: $store.preferredToolbarProvider) {
                    Text("Codex").tag("codex")
                    Text("Claude").tag("claude")
                }
                .padding(.leading, 12)
                Text("Only the selected provider appears in the menu bar. Both remain in the usage panel.")
                    .font(.system(size: 10)).foregroundColor(Palette.muted).fixedSize(horizontal: false, vertical: true)
            }
            Toggle("Show Codex", isOn: $store.codexEnabled)
            Toggle("Show Claude when available", isOn: $store.claudeEnabled)
            Toggle("Launch at login", isOn: Binding(get: { store.loginEnabled }, set: store.setLogin))
            ResetNotificationSettings(insights: store.insights)
            Divider().overlay(Palette.border)
            Button("Copy Claude connection command") {
                let path = Bundle.main.resourceURL?.appendingPathComponent("install-claude-bridge.py").path ?? "scripts/install-claude-bridge.py"
                let command = "python3 '" + path.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
            }.buttonStyle(.plain).foregroundColor(Palette.blue)
            Text("Run in Terminal, then restart Claude Code and send a prompt. Claude appears once quota data is available.")
                .font(.system(size: 10)).foregroundColor(Palette.muted).fixedSize(horizontal: false, vertical: true)
            Text("Quota is the provider’s allowance. Exact subscription tokens remaining are not reported.")
                .font(.system(size: 10)).foregroundColor(Palette.muted).fixedSize(horizontal: false, vertical: true)
            if let error = store.loginError { Text(error).font(.system(size: 10)).foregroundColor(Palette.orange) }
        }.font(.system(size: 11)).toggleStyle(.switch).controlSize(.mini).padding(16)
            .background(Palette.card).cornerRadius(14)
    }
}

private struct ProviderCard: View {
    let snapshot: ProviderSnapshot
    let now: Date
    let resetCheck: ResetCheckResult?
    let checking: Bool
    let checkDisabled: Bool
    let onCheck: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var accent: Color { Palette.blue }
    var limiting: UsageWindow? {
        snapshot.windows.first { $0.id == "primary" || $0.id == "session" }
            ?? snapshot.windows.min { ($0.durationMinutes ?? Int.max) < ($1.durationMinutes ?? Int.max) }
    }
    var stale: Bool { snapshot.updatedAt.map { now.timeIntervalSince($0) > 900 } ?? true }
    var expired: Bool { snapshot.windows.contains { $0.resetsAt.map { $0 <= now } ?? false } }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 10) {
                if snapshot.provider == .codex, let icon = Brand.codex {
                    Image(nsImage: icon).resizable().interpolation(.high).frame(width: 38, height: 38)
                } else if snapshot.provider == .claude, let icon = Brand.claude {
                    Image(nsImage: icon).resizable().interpolation(.high).frame(width: 38, height: 38)
                } else {
                    Image(systemName: snapshot.provider == .codex ? "terminal" : "sparkle").font(.system(size: 23)).foregroundColor(accent).frame(width: 38, height: 38)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(snapshot.provider.title).font(.system(size: 17, weight: .semibold))
                    Text(snapshot.windows.isEmpty ? "Waiting for your first session" : "Subscription allowance").font(.system(size: 10)).foregroundColor(Palette.muted)
                }
                Spacer()
                Button {
                    NSWorkspace.shared.open(URL(string: snapshot.provider == .codex ? "https://chatgpt.com/codex/settings/usage" : "https://claude.ai/settings/usage")!)
                } label: { Image(systemName: "arrow.up.right").font(.system(size: 11)).foregroundColor(Palette.muted) }.buttonStyle(.plain).help("Open account usage")
            }
            if let window = limiting {
                HStack(alignment: .lastTextBaseline, spacing: 8) {
                    Text(expired ? "—" : "\(Int(window.remainingPercent.rounded()))%")
                        .font(.system(size: 44, weight: .medium)).monospacedDigit().tracking(-2)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(expired ? "Reset pending" : "remaining").font(.system(size: 12, weight: .medium))
                        Text(stale ? "Last recorded usage" : "\(shortTitle(window)) limit")
                            .font(.system(size: 10)).foregroundColor(Palette.muted)
                    }
                    Spacer()
                    if window.remainingPercent <= 10 && !expired {
                        Text("Low quota").font(.system(size: 10, weight: .medium)).foregroundColor(Palette.orange)
                    }
                }.opacity(stale || expired ? 0.6 : 1)
                HStack(spacing: 10) {
                    Image(systemName: "arrow.clockwise").font(.system(size: 14)).foregroundColor(accent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("NEXT RESET").font(.system(size: 8, weight: .semibold)).tracking(1).foregroundColor(Palette.muted)
                        Text(resetText(window.resetsAt)).font(.system(size: 13, weight: .medium)).monospacedDigit()
                    }
                    Spacer()
                    if let date = window.resetsAt {
                        Text(date.formatted(date: .omitted, time: .shortened)).font(.system(size: 11)).foregroundColor(Palette.muted)
                    }
                }.padding(12).background(accent.opacity(0.07)).cornerRadius(10)
                VStack(spacing: 16) {
                    ForEach(snapshot.windows) { window in quota(window) }
                }
                if let tokens = snapshot.contextRemainingTokens {
                    HStack {
                        Text("Conversation context left").foregroundColor(Palette.muted)
                        Spacer()
                        Text("≈ " + tokens.formatted()).monospacedDigit()
                    }.font(.system(size: 10))
                }
                HStack(spacing: 5) {
                    Circle().fill(stale || expired ? Palette.orange : Palette.mint).frame(width: 4, height: 4)
                    Text(freshness).font(.system(size: 9))
                    Spacer()
                    Text(snapshot.source).font(.system(size: 9)).lineLimit(1)
                }.foregroundColor(Palette.muted)
            } else {
                Text(snapshot.message ?? "Start Codex to see your quota and reset times.")
                    .font(.system(size: 12)).foregroundColor(Palette.muted).fixedSize(horizontal: false, vertical: true).lineSpacing(4)
            }
            Divider().overlay(Palette.border)
            Button(action: onCheck) {
                HStack(spacing: 6) {
                    if checking { ProgressView().controlSize(.mini) }
                    else { Image(systemName: "arrow.clockwise") }
                    Text(checking ? "Checking account…" : "Check reset now")
                    Spacer()
                }.font(.system(size: 11, weight: .medium)).foregroundColor(accent)
            }.buttonStyle(.plain).disabled(checkDisabled)
            if let result = resetCheck {
                VStack(alignment: .leading, spacing: 5) {
                    Text(result.title).font(.system(size: 11, weight: .semibold))
                        .foregroundColor(result.status == .available || result.status == .confirmed ? accent : Palette.orange)
                    Text(result.message).font(.system(size: 10)).foregroundColor(Palette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Checked \(result.checkedAt.formatted(date: .omitted, time: .shortened))")
                        .font(.system(size: 9)).foregroundColor(Palette.muted)
                }
            }
        }.padding(18).background(RoundedRectangle(cornerRadius: 14).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Palette.border, lineWidth: 1))
    }
    private func shortTitle(_ window: UsageWindow) -> String {
        window.title.replacingOccurrences(of: " window", with: "").replacingOccurrences(of: "Weekly", with: "Weekly")
    }
    private func quota(_ window: UsageWindow) -> some View {
        let due = window.resetsAt.map { $0 <= now } ?? false
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(shortTitle(window)).font(.system(size: 11, weight: .medium))
                Spacer()
                Text(due ? "Awaiting reset" : "\(Int(window.remainingPercent.rounded()))% left").font(.system(size: 11, weight: .semibold)).monospacedDigit().foregroundColor(due ? Palette.muted : accent)
            }
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(Palette.border)
                    Capsule().fill(window.remainingPercent <= 10 ? Palette.orange : accent)
                        .frame(width: geometry.size.width * window.remainingPercent / 100).opacity(due ? 0.25 : 1)
                        .animation(reduceMotion ? nil : .easeInOut(duration: 0.5), value: window.remainingPercent)
                }
            }.frame(height: 5)
            HStack(spacing: 4) {
                Image(systemName: "clock").font(.system(size: 9))
                Text(resetText(window.resetsAt)).font(.system(size: 10)).monospacedDigit()
            }.foregroundColor(due ? Palette.orange : Palette.muted)
                .help(window.resetsAt?.formatted(date: .abbreviated, time: .shortened) ?? "Reset time unavailable")
        }
    }
    private func resetText(_ date: Date?) -> String {
        guard let date else { return "Reset time unavailable" }
        let seconds = max(0, Int(date.timeIntervalSince(now)))
        guard seconds > 0 else { return "Reset due · waiting for fresh usage" }
        let days = seconds / 86400, hours = seconds % 86400 / 3600, minutes = seconds % 3600 / 60
        if days > 0 { return "Resets in \(days)d \(hours)h" }
        if hours > 0 { return "Resets in \(hours)h \(minutes)m" }
        return "Resets in \(minutes)m \(seconds % 60)s"
    }
    private var freshness: String {
        guard let date = snapshot.updatedAt else { return "Not connected" }
        let minutes = max(0, Int(now.timeIntervalSince(date) / 60))
        if minutes == 0 { return "Just updated" }
        if minutes < 60 { return "Updated \(minutes)m ago" }
        if minutes < 1440 { return "Updated \(minutes / 60)h ago" }
        return "Updated \(minutes / 1440)d ago"
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate, UNUserNotificationCenterDelegate {
    private var store: UsageStore!
    private var statusItems: [String: NSStatusItem] = [:]
    private let popover = NSPopover()
    private let panelController = NSHostingController(rootView: AnyView(EmptyView()))
    private var observer: AnyCancellable?
    private var timer: Timer?

    private func startMenuBar(demo: Bool = false) {
        store = UsageStore(demo: demo || ProcessInfo.processInfo.arguments.contains("--preview"))
        popover.behavior = .transient
        popover.delegate = self
        popover.contentViewController = panelController
        observer = store.objectWillChange.sink { [weak self] _ in
            DispatchQueue.main.async { self?.updateMenuBar() }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.updateMenuBar() }
        }
        updateMenuBar()
    }
    private func updateMenuBar() {
        let availableSnapshots = store.availableSnapshots
        let snapshots = store.toolbarMode == "one"
            ? availableSnapshots.filter { $0.provider.rawValue == store.preferredToolbarProvider }
            : availableSnapshots
        let keys = snapshots.isEmpty ? ["empty"] : snapshots.map { $0.provider.rawValue }
        for key in Array(statusItems.keys) where !keys.contains(key) {
            if let item = statusItems.removeValue(forKey: key) { NSStatusBar.system.removeStatusItem(item) }
        }
        for key in keys {
            let item: NSStatusItem
            if let existing = statusItems[key] { item = existing }
            else {
                item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
                statusItems[key] = item
            }
            guard let button = item.button else { continue }
            button.target = self
            button.action = #selector(togglePopover(_:))
            button.imagePosition = .imageLeading
            button.imageScaling = .scaleNone
            button.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
            if let snapshot = snapshots.first(where: { $0.provider.rawValue == key }) {
                button.image = snapshot.provider == .codex ? Brand.largeCodexMenu : Brand.largeClaudeMenu
                let value = store.menuValue(snapshot)
                button.title = store.menuStyle == "icon" ? "" : " " + (store.menuStyle == "quota" ? String(value.split(separator: "·").first ?? "—").trimmingCharacters(in: .whitespaces) : value)
                button.toolTip = "\(snapshot.provider.title) · short-window quota remaining and time until reset"
            } else {
                button.image = Brand.genericMenu
                button.title = ""
                button.toolTip = "TokenBar · waiting for usage"
            }
            button.setAccessibilityLabel(button.toolTip)
        }
    }
    @objc private func togglePopover(_ sender: NSStatusBarButton) {
        if popover.isShown { popover.performClose(sender) }
        else {
            NSApplication.shared.activate(ignoringOtherApps: true)
            panelController.rootView = AnyView(DashboardView(store: store))
            panelController.view.layoutSubtreeIfNeeded()
            let size = panelController.view.fittingSize
            popover.contentSize = NSSize(width: 380, height: min(730, max(200, size.height)))
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }
    func popoverDidClose(_ notification: Notification) {
        // Keep AppKit's controller stable and release only the periodic SwiftUI content.
        // Defer until the close callback finishes; a rapid reopen must keep its new content.
        DispatchQueue.main.async { [weak self] in
            guard let self, !self.popover.isShown else { return }
            self.panelController.rootView = AnyView(EmptyView())
        }
    }

    func applicationWillTerminate(_ notification: Notification) { store?.insights.shutdown() }

    func applicationDidFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
        NSApplication.shared.setActivationPolicy(.accessory)
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("--check-popover") {
            startMenuBar(demo: true)
            Task { @MainActor in
                for tab in ["Usage", "History", "Connect", "Usage"] {
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    guard let button = statusItems.values.first?.button else { print("No status button"); exit(1) }
                    togglePopover(button)
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    guard popover.isShown else { print("Panel failed to remain open for \(tab)"); exit(1) }
                    store.selectedTab = tab
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    guard popover.isShown else { print("Panel closed during \(tab) navigation"); exit(1) }
                    popover.performClose(nil)
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                    guard !popover.isShown, popover.contentViewController != nil else {
                        print("Panel close lifecycle failed for \(tab): shown=\(popover.isShown), controller=\(popover.contentViewController != nil)")
                        exit(1)
                    }
                }
                print("Popover open, tab changes, close and reopen checks passed.")
                exit(0)
            }
            return
        }
        if arguments.contains("--diagnose") {
            Task {
                for provider in UsageProvider.allCases {
                    let snapshot = await UsageService().load(provider: provider)
                    print("\(provider.title): source=\(snapshot.source), windows=\(snapshot.windows.count)")
                    for window in snapshot.windows {
                        print("  \(window.title): remaining=\(window.remainingPercent)% reset=\(window.resetsAt.map { ISO8601DateFormatter().string(from: $0) } ?? "unknown")")
                    }
                    if let message = snapshot.message { print("  \(message)") }
                }
                exit(0)
            }
            return
        }
        guard let index = arguments.firstIndex(of: "--screenshot"), arguments.count > index + 1 else { startMenuBar(); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            let previewStore = UsageStore(demo: true)
            if arguments.contains("--codex-only") { previewStore.snapshots = previewStore.snapshots.filter { $0.provider == .codex } }
            let content: AnyView
            if arguments.contains("--with-menu-bar") {
                content = AnyView(VStack(spacing: 12) {
                    HStack(spacing: 14) {
                        Spacer()
                        ForEach(previewStore.snapshots, id: \.provider) { snapshot in
                            HStack(spacing: 5) {
                                Image(nsImage: Brand.genericMenu).renderingMode(.template)
                                    .frame(width: 20, height: 20)
                                Text(previewStore.menuValue(snapshot))
                                    .font(.system(size: 11, weight: .medium)).monospacedDigit()
                            }
                        }
                    }.padding(.horizontal, 14).padding(.vertical, 4)
                        .frame(width: 380).foregroundColor(.primary)
                        .background(Palette.card).cornerRadius(8)
                    DashboardView(store: previewStore).cornerRadius(14)
                }.padding(12).background(Palette.background))
            } else {
                content = AnyView(DashboardView(store: previewStore))
            }
            let view = NSHostingView(rootView: content)
            let size = view.fittingSize
            view.frame = NSRect(origin: .zero, size: size)
            guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(1) }
            view.cacheDisplay(in: view.bounds, to: bitmap)
            guard let data = bitmap.representation(using: .png, properties: [:]) else { exit(1) }
            do { try data.write(to: URL(fileURLWithPath: arguments[index + 1])); exit(0) }
            catch { fputs("Screenshot failed: \(error)\n", stderr); exit(1) }
        }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .list]
    }
}
