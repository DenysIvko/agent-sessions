import Foundation
import AppKit

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { fputs("FAIL: \(message)\n", stderr); exit(1) }
}

private func session(_ id: String = "a", source: String = "codex", running: Bool = false,
                     status: String = "completed", start: Double = 90, end: Double? = 95,
                     turn: String = "turn-1", unread: Bool? = nil) -> AgentSession {
    AgentSession(id: id, source: source, title: "Test session", project: "Project", running: running,
                 status: status, startedAt: start, endedAt: end, turnId: turn, url: nil,
                 projectId: "project-id", unread: unread, activityAt: start, branch: nil, resumeCommand: nil)
}

private func snapshot(_ time: Double, _ sessions: [AgentSession], errors: [String: String] = [:]) -> DashboardSnapshot {
    DashboardSnapshot(service: "agent-sessions", checkedAt: time, sessions: sessions,
                      sourceErrors: errors, error: errors.isEmpty ? nil : "Some data unavailable")
}

@main
enum MonitorTests {
    static func main() throws {
        var tracker = CompletionTracker()
        let running = session(running: true, status: "inProgress", end: nil)
        expect(tracker.update(snapshot(100, [session("old"), running])).isEmpty, "startup must not notify about old results")
        expect(tracker.update(snapshot(103, [session(end: 102)])).count == 1, "running to completed notifies")
        expect(tracker.update(snapshot(106, [session(end: 102)])).isEmpty, "a completion must notify once")
        expect(tracker.update(snapshot(109, [session(start: 107, end: 108, turn: "turn-2")])).count == 1,
               "a run completed between polls must notify")
        expect(tracker.update(snapshot(112, [session(start: 107, end: 108, turn: "turn-2")])).isEmpty,
               "a second run must also deduplicate")

        for (status, outcome) in [("failed", "failed"), ("interrupted", "stopped")] {
            var tracker = CompletionTracker()
            _ = tracker.update(snapshot(100, [running]))
            let events = tracker.update(snapshot(103, [session(status: status, end: nil)]))
            expect(events.count == 1 && events[0].outcome == outcome, "\(status) must retain its outcome")
        }
        var disappearance = CompletionTracker()
        _ = disappearance.update(snapshot(100, [running]))
        expect(disappearance.update(snapshot(103, [])).isEmpty, "archiving or disappearing is not completion")
        _ = disappearance.update(snapshot(106, [running]))
        expect(disappearance.update(snapshot(109, [session(status: "inProgress", end: nil)])).isEmpty,
               "an inactive or crashed process is not a successful completion")

        var partial = CompletionTracker()
        let claudeRun = session("claude:a", source: "claude", running: true, status: "inProgress", end: nil)
        _ = partial.update(snapshot(100, [running, claudeRun]))
        let freshClaude = session("claude:a", source: "claude", end: 102)
        let partialEvents = partial.update(snapshot(103, [session(end: 102), freshClaude], errors: ["codex": "stale"]))
        expect(partialEvents.map(\.id) == ["claude:a"], "ignore stale data while monitoring healthy sources")
        expect(partial.update(snapshot(106, [session(end: 104), freshClaude])).map(\.id) == ["a"],
               "notify after a source recovers without duplicating the healthy source")

        var firstRecovery = CompletionTracker()
        _ = firstRecovery.update(snapshot(100, [], errors: ["claude": "unavailable"]))
        expect(firstRecovery.update(snapshot(103, [freshClaude])).isEmpty,
               "the first healthy snapshot of a source establishes its baseline")
        expect(firstRecovery.update(snapshot(106, [freshClaude, session("late-old", end: 80)])).isEmpty,
               "old sessions appearing late must not create notifications")

        let sample = Data("""
          {"service":"agent-sessions","checkedAt":100,"sourceErrors":{},"sessions":[
            {"id":"claude:x","source":"claude","title":"Example","project":"Example","running":false,
             "status":null,"startedAt":null,"endedAt":null,"url":null,"unread":null}]}
          """.utf8)
        let decoded = try JSONDecoder().decode(DashboardSnapshot.self, from: sample)
        expect(decoded.sessions[0].outcome == nil, "unknown Claude state must remain unknown")
        expect(decoded.sessions[0].favorite == nil && decoded.favoriteSessions == nil, "snapshots without favorites remain readable")
        let favoritesSample = Data("""
          {"checkedAt":110,"sessions":[],"favoriteSessions":[
            {"id":"old","source":"claude","title":"Old favorite","project":"Project","running":false,
             "favorite":true,"status":"completed","endedAt":109}]}
          """.utf8)
        let favorites = try JSONDecoder().decode(DashboardSnapshot.self, from: favoritesSample)
        expect(favorites.favoriteSessions?.first?.favorite == true, "saved flags decode for the native list")
        expect(favorites.sessionsIncludingFavorites.map(\.id) == ["old"], "old favorites remain in the default tray after midnight")
        var overlapping = snapshot(110, [session("today"), session("ordinary")])
        overlapping.favoriteSessions = [session("today"), session("yesterday")]
        expect(overlapping.sessionsIncludingFavorites.map(\.id) == ["today", "ordinary", "yesterday"],
               "today and favorites combine without duplicate sessions")
        expect(traySessions(favorites.favoriteSessions ?? [], query: "old").count == 1,
               "favorites use the same native search")
        var favoriteTracker = CompletionTracker()
        _ = favoriteTracker.update(snapshot(100, []))
        expect(favoriteTracker.update(favorites).isEmpty, "loading old favorites does not generate completion alerts")
        let codexColor = identityComponents(kind: "session", id: "fixed-session-id")
        let projectColor = identityComponents(kind: "project", id: "fixed-project-id")
        expect(codexColor.hue == 318 && codexColor.saturation == 0.66, "native session colors match the web library")
        expect(projectColor.hue == 27 && projectColor.saturation == 0.74, "native project colors match the web library")
        let mixed = [session("old"), running, freshClaude]
        expect(traySessions(mixed).first?.running == true, "native list places running work first")
        expect(traySessions(mixed, query: "  CLAUDE CODE  ").count == 1, "search is case-insensitive and covers sources")
        var reviews = SessionReviews()
        let unread = session("unread", unread: true)
        let read = session("read", unread: false)
        let oldClaude = session("claude:old", source: "claude")
        let initial = snapshot(100, [unread, read, running, oldClaude])
        reviews.update(initial, finished: [])
        expect(reviews.newSessions(in: initial).map(\.id) == ["unread", running.id],
               "New includes running work and unread results, excluding read and unknown old results")
        reviews.update(initial, finished: [], delivered: [oldClaude.completionID])
        expect(reviews.newSessions(in: initial).map(\.id) == ["unread", running.id, "claude:old"],
               "existing delivered Claude notifications seed New on startup")
        reviews.markReviewed(unread)
        reviews.markReviewed(oldClaude)
        reviews = try JSONDecoder().decode(SessionReviews.self, from: JSONEncoder().encode(reviews))
        reviews.update(initial, finished: [], delivered: [oldClaude.completionID])
        expect(reviews.newSessions(in: initial).map(\.id) == [running.id],
               "reviews survive restart, while running work remains in New")
        reviews.markReviewed(running)
        expect(reviews.newSessions(in: initial).map(\.id) == [running.id], "opening running work does not remove it from New")
        let again = session("claude:old", source: "claude", start: 101, end: 102, turn: "turn-2")
        let next = snapshot(103, [unread, read, again])
        reviews.update(next, finished: [again, read])
        expect(reviews.newSessions(in: next).map(\.id) == ["claude:old"],
               "a fresh completion returns to New, while an already-read result does not")
        let externallyRead = snapshot(106, [session("unread", end: 105, turn: "turn-2", unread: false), again])
        reviews.update(externallyRead, finished: externallyRead.sessions)
        expect(reviews.newSessions(in: externallyRead).map(\.id) == ["claude:old"],
               "Codex read receipts clear results checked directly in the source app")
        reviews.update(snapshot(109, [], errors: ["claude": "offline"]), finished: [])
        expect(reviews.newSessions(in: next).map(\.id) == ["claude:old"], "a source outage keeps pending reviews")
        reviews.update(snapshot(112, []), finished: [])
        expect(reviews.newSessions(in: snapshot(113, [again])).isEmpty, "removed sessions do not return as new")

        // Exercise the native view without showing a window or opening source apps.
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.prohibited)
        let tray = TrayViewController()
        expect(!tray.isViewLoaded, "startup status is read before the tray panel loads")
        expect(tray.selectedView == "New" && tray.rowCount == 0 && tray.newCount == 0,
               "notification status can read the default tray state before the first snapshot")
        var viewSnapshot = snapshot(120, [unread, running])
        viewSnapshot.favoriteSessions = [oldClaude]
        tray.update(viewSnapshot, newSessions: [unread, running], notificationState: "Allowed")
        expect(tray.selectedView == "New" && tray.rowCount == 2, "the tray defaults to New with running work")
        var views = [tray.view]
        var tabs: NSSegmentedControl?
        var table: NSTableView?
        var helpButton: NSButton?
        var searchField: NSSearchField?
        while !views.isEmpty {
            let view = views.removeLast()
            if let control = view as? NSSegmentedControl, control.accessibilityLabel() == "Session view" { tabs = control }
            if let control = view as? NSTableView { table = control }
            if let button = view as? NSButton, button.title == "Help" { helpButton = button }
            if let field = view as? NSSearchField { searchField = field }
            expect(view.accessibilityLabel() != "Session source" && view.accessibilityLabel() != "Session status",
                   "the redundant source and status filter row is removed")
            views.append(contentsOf: view.subviews)
        }
        expect(tabs?.segmentCount == 3, "New, All and Favorites tabs are accessible")
        var helpOpened = false
        var selectedViews: [String] = []
        tray.onSelectView = { selectedViews.append($0) }
        tray.onHelp = { helpOpened = true }
        expect(helpButton != nil, "the tray exposes Help")
        helpButton!.performClick(nil)
        expect(helpOpened, "Help opens the tutorial callback")
        tabs!.selectedSegment = 1
        expect(NSApp.sendAction(tabs!.action!, to: tabs!.target, from: tabs), "All is connected to its handler")
        expect(tray.selectedView == "All" && tray.rowCount == 3, "All includes running sessions and older favorites")
        tabs!.selectedSegment = 2
        expect(NSApp.sendAction(tabs!.action!, to: tabs!.target, from: tabs), "Favorites is connected to its handler")
        expect(tray.selectedView == "Favorites" && tray.rowCount == 1, "Favorites includes saved sessions across days")
        expect(selectedViews == ["all", "favorites"], "view analytics uses fixed view names")
        var searches: [String] = []
        tray.onSearch = { searches.append($0) }
        searchField!.stringValue = "private search text"
        tray.controlTextDidEndEditing(Notification(name: NSControl.textDidEndEditingNotification))
        tray.controlTextDidEndEditing(Notification(name: NSControl.textDidEndEditingNotification))
        searchField!.stringValue = ""
        tray.controlTextDidEndEditing(Notification(name: NSControl.textDidEndEditingNotification))
        expect(searches == ["applied", "cleared"], "search analytics deduplicates focus changes and excludes query text")
        tray.showNewSessions()
        expect(tray.selectedView == "New" && tray.rowCount == 2, "reopening the tray returns to New")
        var archivedID: String?
        var openedID: String?
        tray.onArchiveSession = { archivedID = $0.id }
        tray.onOpenSession = { openedID = $0.id }
        for row in 0..<tray.rowCount {
            views = [tray.tableView(table!, viewFor: nil, row: row)!]
            var archiveButton: NSButton?
            while !views.isEmpty {
                let view = views.removeLast()
                if let button = view as? NSButton, button.accessibilityLabel()?.hasPrefix("Archive ") == true { archiveButton = button }
                views.append(contentsOf: view.subviews)
            }
            expect(archiveButton?.isEnabled == true, "every row has a visible archive action, including running work")
            expect(NSApp.sendAction(archiveButton!.action!, to: archiveButton!.target, from: archiveButton), "archive button invokes its handler")
            expect(archivedID == (row == 0 ? running.id : unread.id) && openedID == nil, "archive targets its row without opening it")
        }
        print("Completion monitor checks passed: startup, repeat runs, fast runs, failures, stops, missing sessions, stale sources, recovery and decoding.")
        print("New view checks passed: unread results, Claude alerts, review persistence, repeat runs, source reads and outages.")
        print("Native tray checks passed: New default, All, Favorites, reopen reset and per-row archive actions.")
    }
}
