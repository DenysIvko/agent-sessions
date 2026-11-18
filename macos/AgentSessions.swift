import AppKit
import Foundation
import UserNotifications

private let dashboardURL = URL(string: "http://127.0.0.1:4318")!

private func isSessionLink(_ url: URL) -> Bool {
    (url.scheme == "codex" && url.host == "threads")
        || (url.scheme == "claude" && ["code", "epitaxy", "resume"].contains(url.host ?? ""))
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    private var statusItem: NSStatusItem!
    private let popover = NSPopover()
    private let dashboard = TrayViewController()
    private var timer: Timer?
    private var backend: Process?
    private var backendLog: FileHandle?
    private var tracker = CompletionTracker()
    private var reviews = UserDefaults.standard.data(forKey: "sessionReviews")
        .flatMap { try? JSONDecoder().decode(SessionReviews.self, from: $0) } ?? SessionReviews()
    private var deliveredCompletions = Set<String>()
    private var requestInFlight = false
    private var savingFavorites = Set<String>()
    private var archiving = Set<String>()
    private var lastLaunchAttempt = Date.distantPast
    private var statusMessage = "Connecting to session sources..."
    private let network = URLSession(configuration: .ephemeral)
    private let notifications = UNUserNotificationCenter.current()
    private var notificationState = "Checking permission"
    private var latestSnapshot: DashboardSnapshot?
    private var lastNotificationError: String?
    private var lastNotificationTitle = ""
    private var lastDeliveredTitle = ""
    private var updateInfo: [String: Any]?
    private var lastUpdateCheck = Date.distantPast
    private var notificationsEnabled: Bool {
        get { UserDefaults.standard.object(forKey: "completionNotifications") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "completionNotifications") }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            let image = NSImage(systemSymbolName: "rectangle.grid.2x2", accessibilityDescription: "Agent Sessions")
            image?.isTemplate = true
            button.image = image
            button.imagePosition = .imageLeading
            button.target = self
            button.action = #selector(statusClicked)
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
            button.toolTip = "Agent Sessions - click to open, right-click for options"
        }
        popover.contentViewController = dashboard
        popover.behavior = .transient
        popover.animates = false
        dashboard.onOpenWeb = { [weak self] in self?.openBrowser() }
        dashboard.onHelp = { [weak self] in self?.openTutorial() }
        dashboard.onNotifications = { [weak self] button in
            DispatchQueue.main.async { self?.showMenu(anchor: button) }
        }
        dashboard.onOpenSession = { [weak self] session in self?.openSession(session) }
        dashboard.onArchiveSession = { [weak self] session in self?.archiveSession(session) }
        dashboard.onFavoriteSession = { [weak self] session in self?.setFavorite(session) }
        dashboard.onMarkReviewed = { [weak self] session in self?.markReviewed(session) }
        notifications.delegate = self
        notifications.getDeliveredNotifications { [weak self] items in
            DispatchQueue.main.async {
                guard let self else { return }
                self.deliveredCompletions = Set(items.map { $0.request.identifier })
                if let snapshot = self.latestSnapshot { self.handle(snapshot) }
            }
        }
        updateNotificationState()
        notifications.requestAuthorization(options: [.alert, .sound]) { [weak self] _, _ in
            self?.updateNotificationState()
        }
        poll()
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { [weak self] in self?.checkForUpdates() }
        timer = Timer(timeInterval: 3, repeats: true) { [weak self] _ in self?.poll() }
        RunLoop.main.add(timer!, forMode: .common)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showDashboard()
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        if backend?.isRunning == true { backend?.terminate() }
        try? backendLog?.close()
    }

    @objc private func statusClicked() {
        if NSApp.currentEvent?.type == .rightMouseUp { showMenu() }
        else if popover.isShown { popover.performClose(nil) }
        else { showDashboard() }
    }

    @objc private func showDashboard() {
        guard let button = statusItem.button else { return }
        dashboard.showNewSessions()
        let screen = button.window?.screen ?? NSScreen.main
        let available = screen?.visibleFrame.size ?? NSSize(width: 1200, height: 900)
        popover.contentSize = NSSize(width: min(460, available.width - 32), height: min(620, available.height - 40))
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }

    private func showMenu(anchor: NSView? = nil) {
        let menu = NSMenu()
        let summary = NSMenuItem(title: statusMessage, action: nil, keyEquivalent: "")
        summary.isEnabled = false
        menu.addItem(summary)
        menu.addItem(.separator())
        addItem("Show Sessions", action: #selector(showDashboard), to: menu)
        addItem("Open Web Dashboard", action: #selector(openBrowser), to: menu)
        addItem("Quick Tour", action: #selector(openTutorial), to: menu)
        menu.addItem(.separator())
        let enabled = addItem("Completion Notifications", action: #selector(toggleNotifications), to: menu)
        enabled.state = notificationsEnabled ? .on : .off
        let permission = NSMenuItem(title: "Notifications: \(notificationState)", action: nil, keyEquivalent: "")
        permission.isEnabled = false
        menu.addItem(permission)
        addItem("Send Test Notification", action: #selector(testNotification), to: menu)
        addItem("Notification Settings...", action: #selector(openNotificationSettings), to: menu)
        menu.addItem(.separator())
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        addItem((updateInfo?["version"] as? String).map { "Download Update \($0)" } ?? "Check for Updates", action: #selector(checkForUpdates), to: menu)
        menu.addItem(NSMenuItem(title: "Version \(version)", action: nil, keyEquivalent: ""))
        menu.addItem(.separator())
        addItem("Quit Agent Sessions", action: #selector(quit), to: menu, key: "q")
        if let view = anchor ?? statusItem.button {
            menu.popUp(positioning: nil, at: .zero, in: view)
        }
        updateNotificationState()
    }

    @discardableResult private func addItem(_ title: String, action: Selector, to menu: NSMenu, key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        menu.addItem(item)
        return item
    }

    @objc private func openBrowser() {
        popover.performClose(nil)
        NSWorkspace.shared.open(dashboardURL)
    }

    @objc private func openTutorial() {
        NSWorkspace.shared.open(dashboardURL.appending(queryItems: [URLQueryItem(name: "tutorial", value: "1")]))
        popover.performClose(nil)
    }

    private func openSession(_ session: AgentSession) {
        if let raw = session.url, let url = URL(string: raw), isSessionLink(url) {
            if NSWorkspace.shared.open(url) {
                markReviewed(session)
                popover.performClose(nil)
            }
        } else if let command = session.resumeCommand {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(command, forType: .string)
            dashboard.showFeedback("Resume command copied")
        }
    }

    private func markReviewed(_ session: AgentSession) {
        reviews.markReviewed(session)
        saveReviews()
        notifications.removeDeliveredNotifications(withIdentifiers: [session.completionID])
        if let snapshot = latestSnapshot {
            dashboard.update(snapshot, newSessions: reviews.newSessions(in: snapshot), notificationState: notificationState)
        }
        writeStatus()
    }

    private func saveReviews() {
        if let data = try? JSONEncoder().encode(reviews) { UserDefaults.standard.set(data, forKey: "sessionReviews") }
    }
    @objc private func quit() { NSApp.terminate(nil) }
    @objc private func checkForUpdates() {
        if let raw = updateInfo?["downloadURL"] as? String, let url = URL(string: raw) {
            NSWorkspace.shared.open(url)
            return
        }
        lastUpdateCheck = Date()
        var request = URLRequest(url: dashboardURL.appendingPathComponent("api/update"))
        request.timeoutInterval = 12
        network.dataTask(with: request) { [weak self] data, response, _ in
            guard let data, (response as? HTTPURLResponse)?.statusCode == 200,
                  let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  info["available"] as? Bool == true, let version = info["version"] as? String,
                  let raw = info["downloadURL"] as? String,
                  raw.hasPrefix("https://github.com/DenysIvko/agent-sessions/releases/download/v") else { return }
            DispatchQueue.main.async {
                guard let self else { return }
                self.updateInfo = info
                self.dashboard.showFeedback("Update \(version) available in the tray menu")
                if UserDefaults.standard.string(forKey: "notifiedVersion") != version {
                    let content = UNMutableNotificationContent()
                    content.title = "Agent Sessions update available"
                    content.body = "Version \(version) is ready. Click to download the installer."
                    content.userInfo["updateURL"] = raw
                    self.sendNotification(identifier: "update-\(version)", content: content)
                    UserDefaults.standard.set(version, forKey: "notifiedVersion")
                }
            }
        }.resume()
    }
    private func setFavorite(_ session: AgentSession) {
        guard savingFavorites.insert(session.id).inserted else { return }
        let enabled = session.favorite != true
        var request = URLRequest(url: dashboardURL.appendingPathComponent("api/favorite"))
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("1", forHTTPHeaderField: "X-Session-Dashboard")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["id": session.id, "favorite": enabled])
        network.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.savingFavorites.remove(session.id)
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.dashboard.showFeedback(enabled ? "Saved to Favorites across all days" : "Removed from Favorites")
                } else {
                    let reply = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                    self.dashboard.showFeedback(reply?["error"] as? String ?? error?.localizedDescription ?? "Could not save favorite")
                }
                self.poll()
            }
        }.resume()
    }
    private func archiveSession(_ session: AgentSession) {
        guard archiving.insert(session.id).inserted else { return }
        dashboard.showFeedback("Archiving...")
        var request = URLRequest(url: dashboardURL.appendingPathComponent("api/archive"))
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("1", forHTTPHeaderField: "X-Session-Dashboard")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["id": session.id])
        network.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.archiving.remove(session.id)
                let reply = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: String] }
                let message = reply?["message"] ?? reply?["error"] ?? error?.localizedDescription ?? "Could not save the local archive."
                self.dashboard.showFeedback(message)
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.notifications.removeDeliveredNotifications(withIdentifiers: [session.completionID])
                }
                self.poll()
            }
        }.resume()
    }
    @objc private func toggleNotifications() {
        notificationsEnabled.toggle()
        if notificationsEnabled {
            notifications.requestAuthorization(options: [.alert, .sound]) { [weak self] _, _ in self?.updateNotificationState() }
        }
    }
    @objc private func openNotificationSettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension")!)
    }
    @objc private func testNotification() {
        popover.performClose(nil)
        let content = UNMutableNotificationContent()
        content.title = "Session completed - test notification"
        content.body = "Completion alerts appear here. The tray stays closed."
        content.sound = .default
        sendNotification(identifier: "test-\(UUID().uuidString)", content: content)
    }

    private func updateNotificationState() {
        notifications.getNotificationSettings { [weak self] settings in
            DispatchQueue.main.async {
                self?.notificationState = [UNAuthorizationStatus.authorized: "Allowed", .denied: "Not allowed", .notDetermined: "Awaiting permission", .provisional: "Quiet delivery"][settings.authorizationStatus] ?? "Unknown"
                self?.writeStatus()
            }
        }
    }

    private func poll() {
        if Date().timeIntervalSince(lastUpdateCheck) > 6 * 60 * 60, updateInfo == nil { checkForUpdates() }
        guard !requestInFlight else { return }
        requestInFlight = true
        var request = URLRequest(url: dashboardURL.appendingPathComponent("api/sessions"), cachePolicy: .reloadIgnoringLocalCacheData)
        request.timeoutInterval = 3
        network.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.requestInFlight = false
                if let data, (response as? HTTPURLResponse)?.statusCode == 200,
                   let snapshot = try? JSONDecoder().decode(DashboardSnapshot.self, from: data), snapshot.service == "agent-sessions" {
                    self.handle(snapshot)
                } else {
                    self.statusMessage = "Dashboard reconnecting..."
                    self.statusItem.button?.title = " !"
                    self.statusItem.button?.toolTip = self.statusMessage
                    if let error = error as? URLError, [.cannotConnectToHost, .networkConnectionLost].contains(error.code) {
                        self.startBackend()
                    } else if error == nil {
                        self.statusMessage = "Port 4318 is not serving the current dashboard"
                    }
                    self.writeStatus()
                }
            }
        }.resume()
    }

    private func handle(_ snapshot: DashboardSnapshot) {
        latestSnapshot = snapshot
        let running = snapshot.sessions.filter(\.running).count
        statusMessage = snapshot.error == nil ? "\(snapshot.sessions.count) sessions today - \(running) running" : "Some session data is unavailable"
        statusItem.button?.title = snapshot.error == nil ? (running > 0 ? " \(running)" : "") : " !"
        statusItem.button?.toolTip = "\(statusMessage). Click to open; right-click for options."
        let finished = tracker.update(snapshot)
        let previousReviews = reviews
        reviews.update(snapshot, finished: finished, delivered: deliveredCompletions)
        if reviews != previousReviews { saveReviews() }
        dashboard.update(snapshot, newSessions: reviews.newSessions(in: snapshot), notificationState: notificationState)
        if notificationsEnabled {
            for session in finished {
                let content = UNMutableNotificationContent()
                content.title = "\(session.sourceName) \(session.outcome!)"
                content.subtitle = session.project
                content.body = session.title
                content.sound = .default
                content.threadIdentifier = session.source
                if let url = session.url { content.userInfo["sessionURL"] = url }
                sendNotification(identifier: session.completionID, content: content)
            }
        }
        writeStatus()
    }

    private func sendNotification(identifier: String, content: UNNotificationContent) {
        lastNotificationTitle = content.title
        notifications.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil)) { [weak self] error in
            DispatchQueue.main.async {
                self?.lastNotificationError = error?.localizedDescription
                self?.writeStatus()
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                self?.notifications.getDeliveredNotifications { items in
                    DispatchQueue.main.async {
                        self?.lastDeliveredTitle = items.max(by: { $0.date < $1.date })?.request.content.title ?? ""
                        self?.writeStatus()
                    }
                }
            }
        }
    }

    private func startBackend() {
        guard backend?.isRunning != true, Date().timeIntervalSince(lastLaunchAttempt) > 10 else { return }
        lastLaunchAttempt = Date()
        guard let root = Bundle.main.resourceURL?.appendingPathComponent("dashboard") else {
            statusMessage = "Dashboard resources are missing"
            return
        }
        do {
            let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Agent Sessions-server.log")
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
            backendLog = try FileHandle(forWritingTo: logURL)
            try backendLog?.seekToEnd()
            let process = Process()
            let bundled = Bundle.main.resourceURL!.appendingPathComponent("backend/agent-sessions-server")
            if FileManager.default.isExecutableFile(atPath: bundled.path) {
                process.executableURL = bundled
                process.arguments = []
            } else if let python = [root.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent(".venv/bin/python").path,
                                    "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"].first(where: { FileManager.default.isExecutableFile(atPath: $0) }) {
                process.executableURL = URL(fileURLWithPath: python)
                process.arguments = [root.appendingPathComponent("server.py").path]
            } else {
                statusMessage = "Reinstall Agent Sessions to restore its bundled runtime"
                return
            }
            process.currentDirectoryURL = root
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            environment["AGENT_SESSIONS_NATIVE_HELPER"] = Bundle.main.executableURL?.path
            process.environment = environment
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = backendLog
            process.standardError = backendLog
            try process.run()
            backend = process
        } catch { statusMessage = "Could not start dashboard: \(error.localizedDescription)" }
    }

    private func writeStatus() {
        let directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Agent Sessions")
        let status: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier,
            "status": statusMessage, "nativeRows": dashboard.rowCount, "popoverShown": popover.isShown,
            "newCount": dashboard.newCount, "selectedView": dashboard.selectedView,
            "notificationPermission": notificationState,
            "notificationsEnabled": notificationsEnabled, "ownsServer": backend?.isRunning == true,
            "sessionCount": latestSnapshot?.sessions.count ?? 0,
            "lastNotificationError": lastNotificationError ?? "", "lastNotificationTitle": lastNotificationTitle,
            "lastDeliveredTitle": lastDeliveredTitle, "updatedAt": Date().timeIntervalSince1970]
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: status, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: directory.appendingPathComponent("status.json"), options: .atomic)
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier else { completionHandler(); return }
        DispatchQueue.main.async {
            if let raw = response.notification.request.content.userInfo["updateURL"] as? String,
               raw.hasPrefix("https://github.com/DenysIvko/agent-sessions/releases/download/v"), let url = URL(string: raw) {
                NSWorkspace.shared.open(url)
            } else if let raw = response.notification.request.content.userInfo["sessionURL"] as? String,
               let url = URL(string: raw), isSessionLink(url) {
                if NSWorkspace.shared.open(url),
                   let session = self.latestSnapshot?.sessionsIncludingFavorites.first(where: { $0.url == raw }) {
                    self.markReviewed(session)
                }
            }
            else { self.openBrowser() }
            completionHandler()
        }
    }
}

@main
enum AgentSessionsApp {
    static func main() {
        if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--archive-claude" {
            _ = NSApplication.shared
            NSApp.setActivationPolicy(.accessory)
            ClaudeArchive.run(id: CommandLine.arguments[2])
            return
        }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
