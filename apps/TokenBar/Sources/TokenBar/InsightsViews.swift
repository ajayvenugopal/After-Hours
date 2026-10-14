import SwiftUI
import Charts
import UsageCore

private let quietText = Palette.muted
private let insightTint = Palette.blue

struct ResetNotificationSettings: View {
    @ObservedObject var insights: InsightsController
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Toggle("Notify when quota resets", isOn: Binding(
                get: { insights.notifications && insights.resetNotifications },
                set: { enabled in
                    insights.resetNotifications = enabled
                    if enabled { insights.enableNotifications(true) }
                }))
            Text("Sends an alert when Codex or Claude confirms a new allowance.")
                .font(.system(size: 10)).foregroundColor(quietText).fixedSize(horizontal: false, vertical: true)
            if let error = insights.error {
                Text(error).font(.system(size: 10)).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

struct ResetActivityView: View {
    @ObservedObject var insights: InsightsController
    let now: Date
    var body: some View {
        if let reset = insights.lastReset, now.timeIntervalSince(reset.date) < 86400 {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "checkmark.circle.fill").foregroundColor(insightTint).font(.system(size: 18))
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(reset.provider) · last confirmed reset").font(.system(size: 12, weight: .semibold))
                    Text("\(reset.window) · \(reset.remaining)% at that reset")
                        .font(.system(size: 10)).foregroundColor(quietText)
                }
                Spacer()
                Text(reset.date.formatted(date: .omitted, time: .shortened))
                    .font(.system(size: 10)).foregroundColor(quietText)
            }.padding(14).background(insightTint.opacity(0.08)).cornerRadius(12)
                .accessibilityElement(children: .combine)
        }
    }
}

struct PaceView: View {
    @ObservedObject var insights: InsightsController
    let provider: String
    var body: some View {
        if let pace = insights.pace[provider + ":primary"] {
            HStack(spacing: 8) {
                Image(systemName: "speedometer")
                Text(String(format: "Recent pace: %.1f%% / hour", pace.percentPerHour))
                Text("·")
                Text(pace.hoursUntilExhausted < 1 ? "under 1h at this pace" : String(format: "~%.1fh at this pace", pace.hoursUntilExhausted))
                Spacer()
            }.font(.system(size: 10)).foregroundColor(quietText)
        }
    }
}

struct LocalActivityView: View {
    @ObservedObject var insights: InsightsController
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(insights.servers.filter(\.online)) { server in
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Image(systemName: "desktopcomputer").foregroundColor(insightTint)
                        Text(server.title).fontWeight(.semibold)
                        Spacer()
                        Text("LOCAL").font(.system(size: 8, weight: .bold)).foregroundColor(.mint)
                    }
                    if server.models.isEmpty { Text("Server online · no model loaded").font(.system(size: 11)).foregroundColor(quietText) }
                    ForEach(server.models) { model in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(model.name).font(.system(size: 11)).lineLimit(1)
                            HStack {
                                if let memory = model.memoryBytes { Text(String(format: "%.1f GB GPU memory", memory / 1_073_741_824)) }
                                if let context = model.contextLength { Text("\(context.formatted()) context") }
                            }.font(.system(size: 9)).foregroundColor(quietText)
                        }
                    }
                    if let event = insights.events.last(where: { $0.provider == server.id }), let speed = event.tokensPerSecond {
                        Text(String(format: "Last captured response · %.1f tokens/s", speed)).font(.system(size: 10)).foregroundColor(insightTint)
                    } else { Text("Connect capture to track tokens and speed.").font(.system(size: 10)).foregroundColor(quietText) }
                }.padding(16).background(Palette.card).cornerRadius(15)
            }
            ForEach(insights.providerNames.filter { ["gemini", "custom"].contains($0) }, id: \.self) { name in
                let recorded = insights.todayEvents.filter { $0.provider == name }
                HStack {
                    Image(systemName: name == "gemini" ? "sparkles" : "chart.bar").foregroundColor(insightTint)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(name.capitalized).font(.system(size: 13, weight: .semibold))
                        Text("Captured today · \(recorded.reduce(0) { $0 + $1.inputTokens + $1.outputTokens }.formatted()) tokens").font(.system(size: 10)).foregroundColor(quietText)
                    }
                    Spacer()
                }.padding(15).background(Palette.card).cornerRadius(15)
            }
            if let error = insights.error { Text(error).font(.system(size: 10)).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true) }
        }
    }
}

struct HistoryView: View {
    @ObservedObject var insights: InsightsController
    @State private var selected = "all"
    private var filtered: [UsageEvent] { insights.events.filter { selected == "all" || $0.provider == selected } }
    private var today: [UsageEvent] { filtered.filter { Calendar.current.isDateInToday($0.timestamp) } }
    private var monthEvents: [UsageEvent] { insights.monthEvents.filter { selected == "all" || $0.provider == selected } }
    private var measuredCosts: [Double] { monthEvents.compactMap(\.estimatedCostUSD) }
    private var monthCost: Double { measuredCosts.reduce(0, +) }
    private var days: [Date] { (0..<7).reversed().compactMap { Calendar.current.date(byAdding: .day, value: -$0, to: Calendar.current.startOfDay(for: Date())) } }
    private func count(_ events: [UsageEvent]) -> Int { events.reduce(0) { $0 + $1.inputTokens + $1.outputTokens } }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Activity").font(.system(size: 21, weight: .medium, design: .default))
            Picker("Provider", selection: $selected) {
                Text("All captured providers").tag("all")
                ForEach(insights.providerNames, id: \.self) { Text($0.capitalized).tag($0) }
            }.font(.system(size: 11))
            HStack {
                metric("TODAY", count(today).formatted(), "captured tokens")
                Spacer()
                if !measuredCosts.isEmpty {
                    metric("THIS MONTH", String(format: "$%.2f", monthCost), "recorded / estimated cost")
                }
            }
            Chart {
                ForEach(Array(days), id: \.self) { day in
                    let value = count(filtered.filter { Calendar.current.isDate($0.timestamp, inSameDayAs: day) })
                    BarMark(x: .value("Day", day, unit: .day), y: .value("Tokens", value)).foregroundStyle(insightTint).cornerRadius(3)
                }
            }.chartYAxis { AxisMarks { _ in AxisGridLine(); AxisValueLabel(format: IntegerFormatStyle<Int>.number.notation(.compactName)) } }.chartXAxis { AxisMarks(values: .stride(by: .day)) { _ in AxisValueLabel(format: .dateTime.weekday(.narrow)) } }.frame(height: 120)
            if filtered.isEmpty {
                Text("No captured events yet. Connect a provider or import an event file to begin. History starts when capture is enabled.").font(.system(size: 11)).foregroundColor(quietText)
            }
            if insights.budget > 0 && selected == "all" && !measuredCosts.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    HStack { Text("Monthly budget"); Spacer(); Text(String(format: "$%.2f / $%.0f", insights.monthCost, insights.budget)) }
                    ProgressView(value: min(insights.monthCost / insights.budget, 1)).tint(insights.monthCost >= insights.budget ? .orange : insightTint)
                }.font(.system(size: 10))
            }
            if !measuredCosts.isEmpty {
                Text("Costs cover \(measuredCosts.count) of \(monthEvents.count) events this month. Subscription quotas do not imply a dollar charge.")
                    .font(.system(size: 9)).foregroundColor(quietText).fixedSize(horizontal: false, vertical: true)
            }
            let models = Dictionary(grouping: filtered, by: { $0.provider + " / " + $0.model })
            ForEach(models.keys.sorted(), id: \.self) { model in
                HStack {
                    Text(model).lineLimit(1)
                    Spacer()
                    Text(count(models[model] ?? []).formatted()).monospacedDigit()
                }.font(.system(size: 10)).foregroundColor(quietText)
            }
            Text("QUOTA HISTORY").font(.system(size: 9, weight: .semibold)).tracking(1.2).foregroundColor(quietText)
            let points = insights.observations.filter { $0.windowID == "primary" && $0.date > Date().addingTimeInterval(-86400) }
            if points.isEmpty {
                Text("Quota samples appear as Codex and Claude refresh.").font(.system(size: 10)).foregroundColor(quietText)
            } else {
                Chart(Array(points.enumerated()), id: \.offset) { _, point in
                    PointMark(x: .value("Time", point.date), y: .value("Used", point.usedPercent)).foregroundStyle(by: .value("Provider", point.provider))
                }.chartYScale(domain: 0...100).frame(height: 110)
                Text("Short-window quota used · last 24 hours").font(.system(size: 9)).foregroundColor(quietText)
            }
            HStack {
                Button("Import events", action: insights.importEvents)
                Spacer()
                Button("Export CSV", action: insights.exportCSV)
            }.buttonStyle(.plain).font(.system(size: 11)).foregroundColor(insightTint)
            if let error = insights.error { Text(error).font(.system(size: 10)).foregroundColor(.orange) }
        }
    }
    private func metric(_ title: String, _ value: String, _ subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 8, weight: .semibold)).tracking(1).foregroundColor(quietText)
            Text(value).font(.system(size: 24, weight: .medium, design: .default))
            Text(subtitle).font(.system(size: 8)).foregroundColor(quietText)
        }
    }
}

struct ConnectionsView: View {
    @ObservedObject var insights: InsightsController
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            Text("Connections").font(.system(size: 21, weight: .medium, design: .default))
            Toggle("Discover local model servers", isOn: $insights.localEnabled)
            helper("Ollama", id: "ollama", detail: "Point your client to localhost:11435. Requests forward to Ollama on 11434.")
            helper("LM Studio", id: "lmstudio", detail: "Point your client to localhost:1235/v1. Requests forward to LM Studio on 1234.")
            helper("Gemini CLI", id: "gemini", detail: "Receives local OTLP JSON metrics on 4319. Follow the guide to connect Gemini telemetry.")
            VStack(alignment: .leading, spacing: 8) {
                Text("Gemini API").fontWeight(.semibold)
                Text("Gemini response capture is included as a command-line helper. The guide has exact commands. No account credentials are stored in TokenBar.").font(.system(size: 10)).foregroundColor(quietText)
                Button("Open connection guide", action: insights.openGuide).buttonStyle(.plain).foregroundColor(insightTint)
            }.padding(14).background(Palette.card).cornerRadius(12)
            Divider()
            Toggle("Allow notifications", isOn: Binding(get: { insights.notifications }, set: insights.enableNotifications))
            ResetNotificationSettings(insights: insights)
            HStack { Text("Warn at remaining"); Spacer(); Picker("Threshold", selection: $insights.threshold) { Text("10%").tag(10.0); Text("20%").tag(20.0); Text("30%").tag(30.0) }.frame(width: 85) }
            HStack { Text("Monthly budget (USD)"); Spacer(); TextField("0 = off", value: $insights.budget, format: .number).textFieldStyle(.roundedBorder).frame(width: 85) }
            Text("Alerts use fresh observations. Reset alerts require confirmation from the provider. Costs without prices stay unknown.").font(.system(size: 10)).foregroundColor(quietText)
            if let error = insights.error { Text(error).foregroundColor(.orange).font(.system(size: 10)) }
        }.font(.system(size: 11)).toggleStyle(.switch).controlSize(.mini)
    }
    private func helper(_ title: String, id: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title).fontWeight(.semibold)
                Spacer()
                Button(insights.helpers.contains(id) ? "Stop capture" : "Start capture") {
                    if insights.helpers.contains(id) { insights.stopHelper(id) } else { insights.startHelper(id) }
                }.buttonStyle(.plain).foregroundColor(insightTint)
            }
            Text(detail).font(.system(size: 10)).foregroundColor(quietText).fixedSize(horizontal: false, vertical: true)
        }.padding(14).background(Palette.card).cornerRadius(12)
    }
}
