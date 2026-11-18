import AppKit
import ApplicationServices

// Claude exposes Archive in its UI, but has no public local archive command.
// Use that control so its worktree warnings and source state remain authoritative.
enum ClaudeArchive {
    private static func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
        return value
    }

    private static func label(_ element: AXUIElement) -> String {
        (attribute(element, kAXDescriptionAttribute) as? String)
            ?? (attribute(element, kAXTitleAttribute) as? String) ?? ""
    }

    private static func find(_ root: AXUIElement, matching: (AXUIElement) -> Bool) -> AXUIElement? {
        var queue = [root]
        var index = 0
        while index < queue.count && index < 3000 {
            let element = queue[index]
            index += 1
            if matching(element) { return element }
            queue.append(contentsOf: attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? [])
        }
        return nil
    }

    private static func record(for id: String) -> [String: Any]? {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Claude/claude-code-sessions")
        guard let files = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: nil) else { return nil }
        for case let url as URL in files where url.lastPathComponent.hasPrefix("local_") && url.pathExtension == "json" {
            guard let data = try? Data(contentsOf: url),
                  let row = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            let ids = [row["sessionId"] as? String, row["cliSessionId"] as? String, row["lastAssistantCliSessionId"] as? String]
                .compactMap { $0 } + (row["priorCliSessionIds"] as? [String] ?? [])
            if ids.contains(id) { return row }
        }
        return nil
    }

    private static func wait(until condition: () -> Bool, seconds: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        repeat {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return false
    }

    static func run(id: String) {
        func reply(_ ok: Bool, _ message: String) {
            let data = try! JSONSerialization.data(withJSONObject: ["ok": ok, "message": message])
            FileHandle.standardOutput.write(data)
        }
        guard id.range(of: "^(local_)?[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", options: .regularExpression) != nil else {
            reply(false, "Invalid Claude session ID."); return
        }
        guard AXIsProcessTrusted() else {
            reply(false, "To archive in Claude Code, allow Agent Sessions in System Settings > Privacy & Security > Accessibility, then retry. This lets it press Claude's own Archive control.")
            return
        }
        if record(for: id)?["isArchived"] as? Bool == true { reply(true, "Already archived in Claude Code."); return }
        let url = URL(string: id.hasPrefix("local_") ? "claude://epitaxy/\(id)" : "claude://resume?session=\(id)")!
        guard let appURL = NSWorkspace.shared.urlForApplication(toOpen: url), let bundleID = Bundle(url: appURL)?.bundleIdentifier,
              NSWorkspace.shared.open(url) else {
            reply(false, "Install and sign in to Claude Desktop to archive this session."); return
        }
        var app: NSRunningApplication?
        var sessionID: String?
        let ready = wait(until: {
            app = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first
            sessionID = id.hasPrefix("local_") ? id : record(for: id)?["sessionId"] as? String
            return app != nil && sessionID != nil
        }, seconds: 8)
        guard ready, let app, let sessionID else {
            reply(false, "Open this session in Claude Code first, then retry Archive. Claude has not finished importing it."); return
        }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 1)
        func sessionPage() -> AXUIElement? {
            find(root) { element in
                guard let page = attribute(element, kAXURLAttribute) as? URL else { return false }
                return page.host == "claude.ai" && ["/epitaxy/\(sessionID)", "/claude-code-desktop/\(sessionID)"].contains(page.path)
            }
        }
        var menu: AXUIElement?
        let found = wait(until: {
            guard app.isActive, let page = sessionPage(),
                  let pane = find(page, matching: { label($0) == "Primary pane" }),
                  let toolbar = find(pane, matching: { label($0) == "Session tools" }) else { return false }
            menu = find(toolbar) { label($0).hasPrefix("More options for ") }
            return menu != nil
        }, seconds: 8)
        guard found, let menu, AXUIElementPerformAction(menu, kAXPressAction as CFString) == .success else {
            reply(false, "Could not locate this session's menu in Claude Code. Open it and choose Archive there."); return
        }
        var archive: AXUIElement?
        let menuLabel = label(menu)
        let opened = wait(until: {
            guard app.isActive, let page = sessionPage(),
                  let pane = find(page, matching: { label($0) == "Primary pane" }),
                  let container = find(pane, matching: { element in
                      label(element) == menuLabel && (attribute(element, kAXRoleAttribute) as? String) != kAXPopUpButtonRole
                  }) else { return false }
            archive = find(container) { label($0) == "Archive" }
            return archive != nil
        }, seconds: 3)
        guard opened, app.isActive, sessionPage() != nil, let archive,
              AXUIElementPerformAction(archive, kAXPressAction as CFString) == .success else {
            reply(false, "Could not press Archive in Claude Code."); return
        }
        let archived = wait(until: { record(for: sessionID)?["isArchived"] as? Bool == true }, seconds: 3)
        // Never accept Archive anyway or discard-worktree confirmations automatically.
        reply(archived, archived ? "Archived in Claude Code." : "Claude Code requires an archive confirmation.")
    }
}
