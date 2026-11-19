import Foundation
import CryptoKit

struct AgentSession: Decodable {
    let id: String
    let source: String
    let title: String
    let project: String
    let running: Bool
    let status: String?
    let startedAt: Double?
    let endedAt: Double?
    let turnId: String?
    let url: String?
    let projectId: String?
    let unread: Bool?
    let activityAt: Double?
    let branch: String?
    let resumeCommand: String?
    var favorite: Bool? = nil

    var sourceName: String { ["codex": "Codex", "claude": "Claude Code", "antigravity": "Antigravity"][source] ?? source }
    var outcome: String? {
        guard !running else { return nil }
        return ["completed": "finished", "failed": "failed", "interrupted": "stopped"][status ?? ""]
    }
    var completionID: String {
        "\(id):\(turnId ?? String(startedAt ?? 0)):\(status ?? ""):\(endedAt ?? 0)"
    }
}

// Same SHA-256 hue and saturation selection as the web's pinned color-hash 2.0.2.
func identityComponents(kind: String, id: String) -> (hue: Double, saturation: Double) {
    let bytes = SHA256.hash(data: Data("\(kind):\(id)".utf8))
    let value = bytes.prefix(4).reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
    return (Double(value % 359), [0.58, 0.66, 0.74][Int((value + 359) / 360 % 3)])
}

func traySessions(_ sessions: [AgentSession], query: String = "") -> [AgentSession] {
    let text = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    return sessions.filter { session in
        text.isEmpty || [session.title, session.project, session.sourceName, session.branch ?? "", session.id]
            .joined(separator: " ").lowercased().contains(text)
    }.sorted { a, b in
        let aRank = a.running ? 0 : a.unread == true ? 1 : 2
        let bRank = b.running ? 0 : b.unread == true ? 1 : 2
        if aRank != bRank { return aRank < bRank }
        if a.activityAt != b.activityAt { return (a.activityAt ?? 0) > (b.activityAt ?? 0) }
        return a.id < b.id
    }
}

struct DashboardSnapshot: Decodable {
    let service: String?
    let checkedAt: Double?
    let sessions: [AgentSession]
    let sourceErrors: [String: String]?
    let error: String?
    var favoriteSessions: [AgentSession]? = nil
    var analytics: AnalyticsPreference? = nil

    var sessionsIncludingFavorites: [AgentSession] {
        var seen = Set<String>()
        return (sessions + (favoriteSessions ?? [])).filter { seen.insert($0.id).inserted }
    }
}

struct AnalyticsPreference: Decodable {
    let configured: Bool
    let enabled: Bool
}

struct SessionReviews: Codable, Equatable {
    private var pending: [String: String] = [:]
    private var reviewed: [String: String] = [:]

    mutating func update(_ snapshot: DashboardSnapshot, finished: [AgentSession], delivered: Set<String> = []) {
        let sessions = snapshot.sessionsIncludingFavorites
        let candidates = finished + sessions.filter { delivered.contains($0.completionID) }
        for session in candidates where reviewed[session.id] != session.completionID {
            pending[session.id] = session.completionID
        }
        for session in sessions where snapshot.sourceErrors?[session.source] == nil {
            if session.running || session.unread == false || pending[session.id] != session.completionID {
                pending.removeValue(forKey: session.id)
            }
        }
        if snapshot.sourceErrors?.isEmpty != false {
            let ids = Set(sessions.map(\.id))
            pending = pending.filter { ids.contains($0.key) }
            reviewed = reviewed.filter { ids.contains($0.key) }
        }
    }

    func newSessions(in snapshot: DashboardSnapshot) -> [AgentSession] {
        snapshot.sessionsIncludingFavorites.filter { session in
            session.running || (session.outcome != nil && session.unread != false
                && reviewed[session.id] != session.completionID
                && (session.unread == true || pending[session.id] == session.completionID))
        }
    }

    mutating func markReviewed(_ session: AgentSession) {
        reviewed[session.id] = session.completionID
        if pending[session.id] == session.completionID { pending.removeValue(forKey: session.id) }
    }
}

struct CompletionTracker {
    private var previous: [String: AgentSession] = [:]
    private var lastCheck: [String: Double] = [:]
    private var notified = Set<String>()

    mutating func update(_ snapshot: DashboardSnapshot) -> [AgentSession] {
        guard let checkedAt = snapshot.checkedAt else { return [] }
        var finished: [AgentSession] = []
        for source in ["codex", "claude", "antigravity"] where snapshot.sourceErrors?[source] == nil {
            let sessions = snapshot.sessions.filter { $0.source == source }
            if let baseline = lastCheck[source] {
                for session in sessions where session.outcome != nil {
                    let old = previous[session.id]
                    let observedFinish = old?.running == true
                    let completedSinceCheck = (session.endedAt ?? 0) > baseline
                    let newRun = old != nil && session.turnId != nil && session.turnId != old?.turnId
                        && (session.endedAt ?? 0) >= baseline - 1
                    if (observedFinish || completedSinceCheck || newRun)
                        && old?.completionID != session.completionID
                        && !notified.contains(session.completionID) {
                        finished.append(session)
                        notified.insert(session.completionID)
                    }
                }
            }
            previous = previous.filter { $0.value.source != source }
            for session in sessions { previous[session.id] = session }
            lastCheck[source] = checkedAt
        }
        return finished
    }
}
