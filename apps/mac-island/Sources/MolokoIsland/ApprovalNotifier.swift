import AppKit
import UserNotifications

/// Native macOS notifications for approval requests, with «Одобрить» / «Отклонить» buttons.
///
/// The page tells us which approvals wait (`approval`, `approvalGone`, `approvalsPending`
/// bridge messages); a button press goes back to the page as a `moloko-island` event
/// `{action, approvalId}` — the page holds the signed-in session and CSRF, so it performs the
/// request and answers with `approvalResolved`. Each approval is shown once per app run (and
/// not again while its notification is still in Notification Center). Permission is asked the
/// first time a notification is needed, never at launch.
@MainActor
final class ApprovalNotifier: NSObject, UNUserNotificationCenterDelegate {
    enum Permission: Equatable {
        case unknown, notDetermined, denied, allowed
    }

    private(set) var permission: Permission = .unknown
    /// Sends `{action, approvalId}` to the page.
    var sendToPage: ((_ approvalId: String, _ action: String) -> Void)?
    /// The page is loaded and signed in, so it can take an action now.
    var isPageReady: () -> Bool = { false }
    /// A click on a notification: open the island.
    var onOpenIsland: (() -> Void)?

    /// Nil when not running from an .app bundle (`swift run`): notifications need a bundle id.
    private let center: UNUserNotificationCenter?
    private var notified = Set<String>()
    private var summaries: [String: String] = [:]
    private var waiting: [Approval] = []
    private var asking = false
    private var inFlight: [String: Flight] = [:]
    private var loggedDenied = false

    private struct Approval {
        let id: String
        let summary: String
        let agent: String
    }

    private struct Flight {
        let action: String
        var sent: Bool
        let timeout: Task<Void, Never>
    }

    private static let approvalCategory = "approval"
    private static let failedCategory = "approvalFailed"
    private nonisolated static let idKey = "approvalId"
    /// How long an action may wait for the page (loading, signing in) and for its answer.
    private static let actionTimeout: Double = 30

    override init() {
        center = Bundle.main.bundleURL.pathExtension == "app" && Bundle.main.bundleIdentifier != nil
            ? UNUserNotificationCenter.current() : nil
        super.init()
        guard let center else {
            Log.info("notifications unavailable: not running from an app bundle")
            return
        }
        // Set before launching finishes, so a click that launched the app is delivered to us.
        center.delegate = self
        let approve = UNNotificationAction(
            identifier: "approve", title: "Одобрить", options: [],
            icon: UNNotificationActionIcon(systemImageName: "checkmark")
        )
        let reject = UNNotificationAction(
            identifier: "reject", title: "Отклонить", options: [.destructive],
            icon: UNNotificationActionIcon(systemImageName: "xmark")
        )
        center.setNotificationCategories([
            UNNotificationCategory(identifier: Self.approvalCategory, actions: [approve, reject], intentIdentifiers: []),
            UNNotificationCategory(identifier: Self.failedCategory, actions: [], intentIdentifiers: []),
        ])
        refreshPermission()
        // Approvals still in Notification Center from an earlier run are not shown again.
        center.getDeliveredNotifications { delivered in
            let ids = delivered.compactMap { Self.approvalID(fromIdentifier: $0.request.identifier) }
            Task { @MainActor in self.notified.formUnion(ids) }
        }
    }

    // MARK: From the page

    func approvalAppeared(id: String, summary: String, agent: String) {
        guard center != nil, Self.isValidID(id), !notified.contains(id) else { return }
        notified.insert(id)
        let approval = Approval(id: id, summary: Self.clip(summary, 400), agent: Self.clip(agent, 80))
        summaries[id] = approval.summary
        if permission == .allowed {
            post(approval)
        } else {
            waiting.append(approval)
            askPermission() // also re-checks a denial: the owner may have allowed it in Settings since
        }
    }

    /// The approval stopped being pending (answered anywhere, expired, task cancelled).
    func approvalGone(id: String) {
        guard Self.isValidID(id) else { return }
        summaries[id] = nil
        waiting.removeAll { $0.id == id }
        removeNotifications([Self.identifier(id)])
    }

    /// The full list of pending approvals right after the page loaded: withdraw notifications
    /// of approvals that were answered while the page was not running.
    func syncPending(ids: [String]) {
        let pending = Set(ids)
        center?.getDeliveredNotifications { delivered in
            let stale = delivered.map(\.request.identifier).filter { identifier in
                guard let id = Self.approvalID(fromIdentifier: identifier) else { return false }
                return !pending.contains(id)
            }
            Task { @MainActor in self.removeNotifications(stale) }
        }
    }

    /// The page's answer to an action we sent.
    func actionFinished(id: String, ok: Bool, message: String) {
        guard let flight = inFlight.removeValue(forKey: id) else { return }
        flight.timeout.cancel()
        Log.info("approval \(Self.short(id)) \(flight.action): \(ok ? "done" : "failed")")
        removeNotifications([Self.identifier(id)])
        if !ok {
            postFailure(id: id, action: flight.action, reason: message.isEmpty ? "moloko не принял ответ." : Self.clip(message, 300))
        }
    }

    /// The page became ready (loaded and signed in): send actions that waited for it.
    func pageReady() {
        for (id, flight) in inFlight where !flight.sent {
            send(id)
        }
    }

    /// Another moloko server: its approvals are not ours any more.
    func serverChanged() {
        notified.removeAll()
        summaries.removeAll()
        waiting.removeAll()
        inFlight.values.forEach { $0.timeout.cancel() }
        inFlight.removeAll()
        center?.getDeliveredNotifications { delivered in
            let ours = delivered.map(\.request.identifier).filter { Self.approvalID(fromIdentifier: $0) != nil }
            Task { @MainActor in self.removeNotifications(ours) }
        }
    }

    // MARK: Permission

    /// Updates `permission` without asking (launch, before showing the menu).
    func refreshPermission() {
        center?.getNotificationSettings { settings in
            let status = settings.authorizationStatus
            Task { @MainActor in self.permission = Self.permission(for: status) }
        }
    }

    /// Asks for permission if it was never asked; otherwise just reads the current answer.
    /// Queued approvals are shown once allowed and dropped when not.
    func askPermission() {
        guard let center, !asking else { return }
        asking = true
        center.getNotificationSettings { settings in
            let status = settings.authorizationStatus
            Task { @MainActor in self.permissionChecked(status) }
        }
    }

    private func permissionChecked(_ status: UNAuthorizationStatus) {
        guard status == .notDetermined, let center else {
            permissionAnswered(Self.permission(for: status))
            return
        }
        Log.info("asking for notification permission")
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            let failure = error.map { ($0 as NSError).code }
            Task { @MainActor in
                if let failure { Log.error("notification permission request failed (\(failure))") }
                self.permissionAnswered(granted ? .allowed : .denied)
            }
        }
    }

    private func permissionAnswered(_ answer: Permission) {
        asking = false
        let changed = answer != permission
        permission = answer
        if changed || answer != .denied { Log.info("notification permission: \(answer)") }
        let queued = waiting
        waiting.removeAll()
        if answer == .allowed {
            loggedDenied = false
            queued.forEach(post)
        } else if !queued.isEmpty, !loggedDenied {
            loggedDenied = true
            Log.info("notifications are not allowed; approvals are shown only in the island")
        }
    }

    /// System Settings → Notifications → Moloko Island.
    func openSettings() {
        let id = Bundle.main.bundleIdentifier ?? ""
        let urls = [
            "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=\(id)",
            "x-apple.systempreferences:com.apple.preference.notifications",
        ]
        for text in urls {
            if let url = URL(string: text), NSWorkspace.shared.open(url) { return }
        }
    }

    private nonisolated static func permission(for status: UNAuthorizationStatus) -> Permission {
        switch status {
        case .notDetermined: .notDetermined
        case .denied: .denied
        case .authorized, .provisional, .ephemeral: .allowed
        @unknown default: .denied
        }
    }

    // MARK: Posting

    private func post(_ approval: Approval) {
        let content = UNMutableNotificationContent()
        content.title = "moloko: нужно одобрение"
        if !approval.agent.isEmpty { content.subtitle = "Просит: \(approval.agent)" }
        content.body = approval.summary.isEmpty ? "Агент ждёт вашего ответа." : approval.summary
        content.sound = .default
        content.categoryIdentifier = Self.approvalCategory
        content.threadIdentifier = "approvals"
        content.userInfo = [Self.idKey: approval.id]
        add(UNNotificationRequest(identifier: Self.identifier(approval.id), content: content, trigger: nil), what: "approval \(Self.short(approval.id))")
    }

    private func postFailure(id: String, action: String, reason: String) {
        guard permission == .allowed else { return }
        let content = UNMutableNotificationContent()
        content.title = action == "approve" ? "Не удалось одобрить" : "Не удалось отклонить"
        if let summary = summaries[id], !summary.isEmpty { content.subtitle = summary }
        content.body = reason
        content.sound = .default
        content.categoryIdentifier = Self.failedCategory
        content.threadIdentifier = "approvals"
        content.userInfo = [Self.idKey: id]
        add(UNNotificationRequest(identifier: "approval-failed.\(id)", content: content, trigger: nil), what: "failure note for \(Self.short(id))")
    }

    private func add(_ request: UNNotificationRequest, what: String) {
        center?.add(request) { error in
            let failure = error.map { ($0 as NSError).code }
            Task { @MainActor in
                if let failure {
                    Log.error("notification not posted: \(what) (\(failure))")
                } else {
                    Log.info("notification posted: \(what)")
                }
            }
        }
    }

    private func removeNotifications(_ identifiers: [String]) {
        guard let center, !identifiers.isEmpty else { return }
        center.removeDeliveredNotifications(withIdentifiers: identifiers)
        center.removePendingNotificationRequests(withIdentifiers: identifiers)
    }

    // MARK: Actions

    /// A button or a click on one of our notifications (also used by the debug commands).
    func handleResponse(action: String, approvalId: String?) {
        switch action {
        case "approve", "reject":
            guard let approvalId, Self.isValidID(approvalId) else { return }
            perform(action, id: approvalId)
        case UNNotificationDefaultActionIdentifier, "open":
            Log.info("notification clicked: opening the island")
            onOpenIsland?()
        default:
            break // dismissed
        }
    }

    private func perform(_ action: String, id: String) {
        guard inFlight[id] == nil else { return }
        let timeout = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(Self.actionTimeout * 1_000_000_000))
            guard !Task.isCancelled else { return }
            self?.timedOut(id)
        }
        inFlight[id] = Flight(action: action, sent: false, timeout: timeout)
        if isPageReady() {
            send(id)
        } else {
            Log.info("approval \(Self.short(id)) \(action): waiting for the page")
        }
    }

    private func send(_ id: String) {
        guard let flight = inFlight[id], !flight.sent else { return }
        inFlight[id]?.sent = true
        Log.info("approval \(Self.short(id)) \(flight.action): sent to the page")
        sendToPage?(id, flight.action)
    }

    private func timedOut(_ id: String) {
        guard let flight = inFlight.removeValue(forKey: id) else { return }
        Log.error("approval \(Self.short(id)) \(flight.action): no answer from the page")
        let reason = flight.sent
            ? "moloko не ответил вовремя. Откройте островок и проверьте запрос."
            : "Островок не подключён к moloko. Откройте островок, войдите и ответьте там."
        removeNotifications([Self.identifier(id)])
        postFailure(id: id, action: flight.action, reason: reason)
    }

    // MARK: UNUserNotificationCenterDelegate

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let action = response.actionIdentifier
        let id = response.notification.request.content.userInfo[Self.idKey] as? String
        Task { @MainActor in self.handleResponse(action: action, approvalId: id) }
        completionHandler()
    }

    /// Show banners even while the island is the active app (e.g. its panel has the keyboard).
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .list, .sound])
    }

    // MARK: Helpers

    private nonisolated static func identifier(_ id: String) -> String { "approval.\(id)" }

    private nonisolated static func approvalID(fromIdentifier identifier: String) -> String? {
        identifier.hasPrefix("approval.") ? String(identifier.dropFirst("approval.".count)) : nil
    }

    /// Approval ids are UUIDs; anything else from the page is ignored.
    static func isValidID(_ id: String) -> Bool {
        !id.isEmpty && id.count <= 64 && id.allSatisfy { $0.isHexDigit || $0 == "-" }
    }

    private static func clip(_ text: String, _ limit: Int) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.count > limit ? String(trimmed.prefix(limit - 1)) + "…" : trimmed
    }

    /// First 8 characters of an id for the log.
    private static func short(_ id: String) -> String { String(id.prefix(8)) }

    // MARK: Debug (MOLOKO_ISLAND_DEBUG only)

    /// Lets a test build show notifications without the permission prompt (delivered quietly
    /// to Notification Center).
    func debugRequestProvisional() {
        center?.requestAuthorization(options: [.alert, .sound, .provisional]) { granted, _ in
            Task { @MainActor in
                Log.info("provisional permission: \(granted)")
                self.permissionAnswered(granted ? .allowed : .denied)
            }
        }
    }

    func debugReport() {
        guard let center else {
            Log.info("notifications: unavailable")
            return
        }
        center.getNotificationSettings { settings in
            let status = settings.authorizationStatus.rawValue
            let alert = settings.alertSetting.rawValue
            let style = settings.alertStyle.rawValue
            Task { @MainActor in self.debugReportDelivered("status=\(status) alert=\(alert) style=\(style)") }
        }
    }

    private func debugReportDelivered(_ settings: String) {
        center?.getDeliveredNotifications { delivered in
            let list = delivered.map { "\($0.request.identifier) [\($0.request.content.categoryIdentifier)]" }
            Task { @MainActor in
                Log.info("notifications: \(settings) permission=\(self.permission) delivered=\(list) inFlight=\(self.inFlight.keys.sorted())")
            }
        }
    }

    func debugClear() {
        guard let center else { return }
        center.getDeliveredNotifications { delivered in
            let ours = delivered.map(\.request.identifier)
            Task { @MainActor in
                self.removeNotifications(ours)
                Log.info("notifications cleared: \(ours.count)")
            }
        }
    }
}
