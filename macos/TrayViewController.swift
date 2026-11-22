import AppKit

private func identityColor(kind: String, id: String) -> NSColor {
    let color = identityComponents(kind: kind, id: id)
    return NSColor(name: nil) { appearance in
        let dark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        let lightness = dark ? 0.74 : 0.25
        let brightness = lightness + color.saturation * min(lightness, 1 - lightness)
        let saturation = 2 * (1 - lightness / brightness)
        return NSColor(calibratedHue: color.hue / 360, saturation: saturation, brightness: brightness, alpha: 1)
    }
}

private final class Badge: NSView {
    let label = NSTextField(labelWithString: "")
    var tint = NSColor.secondaryLabelColor

    init() {
        super.init(frame: .zero)
        label.font = .systemFont(ofSize: 10, weight: .medium)
        label.lineBreakMode = .byTruncatingTail
        label.translatesAutoresizingMaskIntoConstraints = false
        addSubview(label)
        NSLayoutConstraint.activate([label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 6),
            label.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -6),
            label.centerYAnchor.constraint(equalTo: centerYAnchor), heightAnchor.constraint(equalToConstant: 19)])
        setContentHuggingPriority(.required, for: .horizontal)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func configure(_ text: String, color: NSColor) {
        label.stringValue = text
        label.textColor = color
        tint = color
        toolTip = text
        invalidateIntrinsicContentSize()
        needsDisplay = true
    }
    override var intrinsicContentSize: NSSize { NSSize(width: label.intrinsicContentSize.width + 12, height: 19) }
    override func draw(_ dirtyRect: NSRect) {
        tint.withAlphaComponent(0.11).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 5, yRadius: 5).fill()
    }
}

private final class SessionCell: NSTableCellView {
    let title = NSTextField(labelWithString: "")
    let detail = NSTextField(labelWithString: "")
    let source = Badge()
    let project = Badge()
    let avatar = NSImageView()
    let spinner = NSProgressIndicator()
    let favorite = NSButton()
    let archive = NSButton()
    var onFavorite: ((AgentSession) -> Void)?
    var onArchive: ((AgentSession) -> Void)?
    private var session: AgentSession?

    override init(frame: NSRect) {
        super.init(frame: frame)
        title.font = .systemFont(ofSize: 13, weight: .medium)
        title.lineBreakMode = .byTruncatingTail
        title.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        detail.font = .systemFont(ofSize: 11)
        detail.textColor = .secondaryLabelColor
        detail.lineBreakMode = .byTruncatingTail
        avatar.translatesAutoresizingMaskIntoConstraints = false
        avatar.imageScaling = .scaleProportionallyDown
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isDisplayedWhenStopped = false
        spinner.translatesAutoresizingMaskIntoConstraints = false
        spinner.setAccessibilityLabel("Running")
        spinner.toolTip = "This session is still running"
        favorite.bezelStyle = .recessed
        favorite.isBordered = false
        favorite.target = self
        favorite.action = #selector(toggleFavorite)
        favorite.setContentHuggingPriority(.required, for: .horizontal)
        favorite.widthAnchor.constraint(equalToConstant: 26).isActive = true
        archive.bezelStyle = .recessed
        archive.isBordered = false
        archive.target = self
        archive.action = #selector(archiveSession)
        archive.image = NSImage(systemSymbolName: "archivebox", accessibilityDescription: nil)
        archive.contentTintColor = .secondaryLabelColor
        archive.setContentHuggingPriority(.required, for: .horizontal)
        archive.widthAnchor.constraint(equalToConstant: 26).isActive = true
        let first = NSStackView(views: [title, source, favorite, archive])
        first.spacing = 8
        let second = NSStackView(views: [project, detail])
        second.spacing = 7
        let lines = NSStackView(views: [first, second])
        lines.orientation = .vertical
        lines.alignment = .leading
        lines.spacing = 6
        lines.translatesAutoresizingMaskIntoConstraints = false
        addSubview(avatar)
        addSubview(spinner)
        addSubview(lines)
        NSLayoutConstraint.activate([
            avatar.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 10), avatar.centerYAnchor.constraint(equalTo: centerYAnchor),
            avatar.widthAnchor.constraint(equalToConstant: 22), avatar.heightAnchor.constraint(equalToConstant: 22),
            spinner.centerXAnchor.constraint(equalTo: avatar.centerXAnchor), spinner.centerYAnchor.constraint(equalTo: avatar.centerYAnchor),
            spinner.widthAnchor.constraint(equalToConstant: 18), spinner.heightAnchor.constraint(equalToConstant: 18),
            lines.leadingAnchor.constraint(equalTo: avatar.trailingAnchor, constant: 10),
            lines.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -10), lines.centerYAnchor.constraint(equalTo: centerYAnchor),
            first.widthAnchor.constraint(equalTo: lines.widthAnchor), second.widthAnchor.constraint(lessThanOrEqualTo: lines.widthAnchor),
            project.widthAnchor.constraint(lessThanOrEqualToConstant: 155),
        ])
        textField = title
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func configure(_ session: AgentSession) {
        self.session = session
        let flagged = session.favorite == true
        favorite.image = NSImage(systemSymbolName: flagged ? "star.fill" : "star", accessibilityDescription: nil)
        favorite.contentTintColor = flagged ? .systemYellow : .secondaryLabelColor
        favorite.toolTip = flagged ? "Remove from favorites" : "Keep in favorites across days"
        favorite.setAccessibilityLabel("\(flagged ? "Unfavorite" : "Favorite") \(session.title)")
        favorite.isEnabled = true
        archive.isEnabled = true
        archive.toolTip = "Hide from Agent Sessions, even if source archival fails. Running work continues."
        archive.setAccessibilityLabel("Archive \(session.title)")
        title.stringValue = session.title
        avatar.image = NSImage(systemSymbolName: session.source == "claude" ? "asterisk" : "chevron.left.forwardslash.chevron.right", accessibilityDescription: session.sourceName)
        avatar.contentTintColor = identityColor(kind: "session", id: session.id)
        avatar.isHidden = session.running
        if session.running { spinner.startAnimation(nil) } else { spinner.stopAnimation(nil) }
        source.configure(session.sourceName, color: session.source == "claude" ? .systemOrange : session.source == "antigravity" ? .systemPurple : .systemTeal)
        project.configure(session.project, color: identityColor(kind: "project", id: session.projectId ?? session.project))
        let status = session.running ? "Running" : ["completed": "Completed", "failed": "Failed", "interrupted": "Stopped"][session.status ?? ""] ?? "Inactive"
        let now = Date().timeIntervalSince1970
        let seconds = max(0, now - (session.running ? session.startedAt ?? now : session.activityAt ?? now))
        let age = seconds < 60 ? "now" : seconds < 3600 ? "\(Int(seconds / 60))m" : "\(Int(seconds / 3600))h"
        detail.stringValue = "\(session.running ? "" : status + " · ")\(age)\(session.unread == true ? " · Unread" : "")"
        detail.setAccessibilityLabel("\(status), \(age)\(session.unread == true ? ", unread" : "")")
        detail.textColor = session.running ? .systemBlue : session.status == "failed" ? .systemRed : .secondaryLabelColor
        toolTip = "\(session.title)\n\(session.project)\(session.branch.map { " · \($0)" } ?? "")\n\(session.url == nil ? "Copy resume command" : "Open in \(session.sourceName)")"
    }
    @objc private func toggleFavorite() {
        guard let session else { return }
        favorite.isEnabled = false
        onFavorite?(session)
    }
    @objc private func archiveSession() {
        guard let session else { return }
        archive.isEnabled = false
        onArchive?(session)
    }
}

final class TrayViewController: NSViewController, NSTableViewDataSource, NSTableViewDelegate, NSSearchFieldDelegate, NSMenuDelegate {
    var onOpenSession: ((AgentSession) -> Void)?
    var onArchiveSession: ((AgentSession) -> Void)?
    var onFavoriteSession: ((AgentSession) -> Void)?
    var onMarkReviewed: ((AgentSession) -> Void)?
    var onOpenWeb: (() -> Void)?
    var onHelp: (() -> Void)?
    var onSelectView: ((String) -> Void)?
    var onSearch: ((String) -> Void)?
    var onNotifications: ((NSButton) -> Void)?
    private let summary = NSTextField(labelWithString: "Connecting...")
    private let tabs: NSSegmentedControl = {
        let control = NSSegmentedControl(labels: ["New", "All", "Favorites"], trackingMode: .selectOne, target: nil, action: nil)
        // Startup notification callbacks read this selection before loadView runs.
        control.selectedSegment = 0
        return control
    }()
    private let search = NSSearchField()
    private var lastSearch = ""
    private let table = NSTableView()
    private let scroll = NSScrollView()
    private let empty = NSTextField(labelWithString: "No sessions with activity today")
    private let footer = NSTextField(labelWithString: "Updates automatically")
    private let notificationsButton = NSButton(title: "Notifications", target: nil, action: nil)
    private var snapshot: DashboardSnapshot?
    private var newSessions: [AgentSession] = []
    private var rows: [AgentSession] = []
    private var contextSession: AgentSession?
    private var feedbackUntil = Date.distantPast
    var rowCount: Int { rows.count }
    var newCount: Int { newSessions.count }
    var selectedView: String { ["New", "All", "Favorites"][tabs.selectedSegment] }

    override func loadView() {
        let root = NSVisualEffectView()
        root.frame = NSRect(x: 0, y: 0, width: 460, height: 620)
        root.material = .popover
        root.state = .active
        view = root
        let heading = NSTextField(labelWithString: "Agent Sessions")
        heading.font = .systemFont(ofSize: 15, weight: .semibold)
        let web = NSButton(title: "Open Web Dashboard", target: self, action: #selector(openWeb))
        web.bezelStyle = .recessed
        web.font = .systemFont(ofSize: 11)
        web.image = NSImage(systemSymbolName: "arrow.up.right", accessibilityDescription: nil)
        web.imagePosition = .imageTrailing
        web.toolTip = "Open the full dashboard with source, project and status filters"
        let spacer = NSView()
        let header = NSStackView(views: [heading, spacer, web])
        header.spacing = 8
        summary.font = .systemFont(ofSize: 11)
        summary.textColor = .secondaryLabelColor
        tabs.target = self
        tabs.action = #selector(tabChanged)
        tabs.segmentStyle = .rounded
        tabs.setAccessibilityLabel("Session view")
        for (index, hint) in ["Running work and results awaiting review", "Today's activity plus saved favorites", "Starred sessions across all days"].enumerated() {
            tabs.setToolTip(hint, forSegment: index)
        }
        search.placeholderString = "Search sessions"
        search.delegate = self
        search.controlSize = .small
        search.setAccessibilityLabel("Search sessions")
        search.toolTip = "Search the selected tab by title, project, source, branch or ID"
        let top = NSStackView(views: [header, summary, tabs, search])
        top.orientation = .vertical
        top.alignment = .leading
        top.spacing = 9
        top.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(top)

        table.headerView = nil
        table.frame = NSRect(x: 0, y: 0, width: 448, height: 400)
        table.autoresizingMask = [.width]
        table.rowHeight = 64
        table.intercellSpacing = NSSize(width: 0, height: 2)
        table.backgroundColor = .clear
        table.style = .plain
        table.columnAutoresizingStyle = .uniformColumnAutoresizingStyle
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("session"))
        column.resizingMask = .autoresizingMask
        table.addTableColumn(column)
        table.delegate = self
        table.dataSource = self
        table.target = self
        table.action = #selector(openSelected)
        table.setAccessibilityLabel("Today's sessions and saved favorites")
        table.menu = NSMenu()
        table.menu?.delegate = self
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.drawsBackground = false
        scroll.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(scroll)
        empty.textColor = .secondaryLabelColor
        empty.font = .systemFont(ofSize: 12)
        empty.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(empty)
        footer.font = .systemFont(ofSize: 10)
        footer.textColor = .secondaryLabelColor
        notificationsButton.target = self
        notificationsButton.action = #selector(notificationOptions)
        notificationsButton.bezelStyle = .recessed
        notificationsButton.font = .systemFont(ofSize: 10)
        notificationsButton.image = NSImage(systemSymbolName: "bell", accessibilityDescription: nil)
        let help = NSButton(title: "Help", target: self, action: #selector(openHelp))
        help.bezelStyle = .recessed
        help.font = .systemFont(ofSize: 10)
        help.toolTip = "Open the quick tour of the tray and dashboard"
        let bottom = NSStackView(views: [footer, NSView(), help, notificationsButton])
        bottom.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(bottom)
        let divider = NSBox()
        divider.boxType = .separator
        divider.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(divider)
        NSLayoutConstraint.activate([
            top.topAnchor.constraint(equalTo: root.topAnchor, constant: 16), top.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16),
            top.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16),
            header.widthAnchor.constraint(equalTo: top.widthAnchor),
            tabs.widthAnchor.constraint(equalTo: top.widthAnchor),
            search.widthAnchor.constraint(equalTo: top.widthAnchor), summary.widthAnchor.constraint(equalTo: top.widthAnchor),
            scroll.topAnchor.constraint(equalTo: top.bottomAnchor, constant: 12), scroll.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 6),
            scroll.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -6), scroll.bottomAnchor.constraint(equalTo: divider.topAnchor, constant: -6),
            divider.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16), divider.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16),
            divider.bottomAnchor.constraint(equalTo: bottom.topAnchor, constant: -7),
            bottom.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16), bottom.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16),
            bottom.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -10), bottom.heightAnchor.constraint(equalToConstant: 24),
            empty.centerXAnchor.constraint(equalTo: scroll.centerXAnchor), empty.centerYAnchor.constraint(equalTo: scroll.centerYAnchor),
        ])
    }

    func update(_ snapshot: DashboardSnapshot, newSessions: [AgentSession], notificationState: String) {
        _ = view
        self.snapshot = snapshot
        self.newSessions = newSessions
        tabs.setLabel("New (\(newSessions.count))", forSegment: 0)
        tabs.setLabel("All (\(snapshot.sessionsIncludingFavorites.count))", forSegment: 1)
        tabs.setLabel("Favorites (\(snapshot.favoriteSessions?.count ?? 0))", forSegment: 2)
        let running = snapshot.sessions.filter(\.running).count
        summary.stringValue = snapshot.error == nil
            ? "\(newSessions.count) new · \(running) running · \(snapshot.sessions.count) today"
            : "Some sources are unavailable - showing last update"
        summary.textColor = snapshot.error == nil ? .secondaryLabelColor : .systemOrange
        notificationsButton.toolTip = "Notifications: \(notificationState)"
        render()
    }

    func showFeedback(_ text: String) {
        footer.stringValue = text
        feedbackUntil = Date().addingTimeInterval(6)
    }

    func showNewSessions() {
        _ = view
        tabs.selectedSegment = 0
        search.stringValue = ""
        lastSearch = ""
        render()
    }

    private func render() {
        guard let snapshot else { return }
        let selected = table.selectedRow >= 0 && table.selectedRow < rows.count ? rows[table.selectedRow].id : nil
        let offset = scroll.contentView.bounds.origin
        let showingNew = tabs.selectedSegment == 0
        let favoritesOnly = tabs.selectedSegment == 2
        let pool = showingNew ? newSessions : favoritesOnly ? snapshot.favoriteSessions ?? [] : snapshot.sessionsIncludingFavorites
        let scope = showingNew ? "Running + awaiting review" : favoritesOnly ? "Favorites · All dates" : "Today + Favorites"
        table.setAccessibilityLabel(showingNew ? "Running sessions and new results awaiting review" : favoritesOnly
            ? "Saved favorites across all days" : "Today's sessions and saved favorites")
        if Date() > feedbackUntil { footer.stringValue = "\(scope) · Auto-refresh every 3s" }
        rows = traySessions(pool, query: search.stringValue)
        table.reloadData()
        if let selected, let index = rows.firstIndex(where: { $0.id == selected }) { table.selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false) }
        scroll.contentView.scroll(to: offset)
        scroll.reflectScrolledClipView(scroll.contentView)
        empty.isHidden = !rows.isEmpty
        empty.stringValue = pool.isEmpty ? (favoritesOnly ? "Star a session to keep it here across days" : showingNew
            ? "No running sessions or new results to review"
            : "No sessions today or saved favorites") : "No matching sessions"
    }

    func numberOfRows(in tableView: NSTableView) -> Int { rows.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let id = NSUserInterfaceItemIdentifier("sessionCell")
        let cell = tableView.makeView(withIdentifier: id, owner: self) as? SessionCell ?? SessionCell(frame: .zero)
        cell.identifier = id
        cell.configure(rows[row])
        cell.onFavorite = { [weak self] session in self?.onFavoriteSession?(session) }
        cell.onArchive = { [weak self] session in self?.onArchiveSession?(session) }
        return cell
    }
    func controlTextDidChange(_ obj: Notification) { render() }
    func controlTextDidEndEditing(_ obj: Notification) {
        if search.stringValue != lastSearch {
            onSearch?(search.stringValue.isEmpty ? "cleared" : "applied")
            lastSearch = search.stringValue
        }
    }
    @objc private func tabChanged() {
        onSelectView?(["new", "all", "favorites"][tabs.selectedSegment])
        render()
    }
    @objc private func openWeb() { onOpenWeb?() }
    @objc private func openHelp() { onHelp?() }
    @objc private func notificationOptions() { onNotifications?(notificationsButton) }
    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        contextSession = nil
        guard rows.indices.contains(table.clickedRow) else { return }
        let session = rows[table.clickedRow]
        contextSession = session
        let open = NSMenuItem(title: "Open in \(session.sourceName)", action: #selector(openContextSession), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        if !session.running && newSessions.contains(where: { $0.id == session.id }) {
            let reviewed = NSMenuItem(title: "Mark reviewed", action: #selector(markContextReviewed), keyEquivalent: "")
            reviewed.target = self
            menu.addItem(reviewed)
        }
        let archive = NSMenuItem(title: "Archive", action: #selector(archiveSelected), keyEquivalent: "")
        archive.target = self
        menu.autoenablesItems = false
        menu.addItem(archive)
    }
    @objc private func openContextSession() {
        if let session = contextSession { onOpenSession?(session) }
    }
    @objc private func markContextReviewed() {
        if let session = contextSession { onMarkReviewed?(session) }
    }
    @objc private func archiveSelected() {
        if let session = contextSession { onArchiveSession?(session) }
    }
    @objc private func openSelected() {
        let row = table.clickedRow >= 0 ? table.clickedRow : table.selectedRow
        if rows.indices.contains(row) { onOpenSession?(rows[row]) }
    }
}
