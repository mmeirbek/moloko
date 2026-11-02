import AppKit
import ServiceManagement

/// The island's state machine: collapsed ⇄ peek ⇄ expanded.
///
/// - collapsed: a black pill hugging the notch (status dot + approvals badge). The window is
///   only as big as the pill; the web view is hidden but alive.
/// - peek: the pill grows a little and says how many actions wait for approval (3 s), when the
///   number of pending approvals goes up while collapsed.
/// - expanded: the rounded panel with the web page. Folds when the pointer is away for 1 s,
///   on Escape or on a click outside — unless pinned. Opened from the keyboard (the global
///   hotkey) or a notification it is "held": the pointer being elsewhere does not fold it.
@MainActor
final class IslandController: NSObject, IslandViewDelegate {
    private(set) var mode: IslandMode = .collapsed
    private(set) var pinned = false {
        didSet { view.setPinned(pinned) }
    }

    let panel: IslandPanel
    let view: IslandView
    let web: WebIsland

    var onChangeAddress: (() -> Void)?
    /// The page is loaded and signed in (a status message said so).
    var onPageReady: (() -> Void)?
    var hotKey: GlobalHotKey?
    var notifier: ApprovalNotifier?
    /// Whether another window of ours (the address window) currently needs the app active.
    var hasOtherWindowOpen: () -> Bool = { false }

    private var geometry: IslandGeometry
    private var status = IslandStatus()
    private var transitionID = 0
    private var hoverTask: Task<Void, Never>?
    private var leaveTask: Task<Void, Never>?
    private var peekTask: Task<Void, Never>?
    private var lastPending = 0
    private var lastPeek = Date.distantPast
    private var modalDepth = 0
    /// Opened from the keyboard or a notification: stays open until Escape, a click outside,
    /// the hotkey or the collapse button, wherever the pointer is.
    private var heldOpen = false
    /// Field the page should focus when the panel opens ("task").
    private var focusOnOpen: String?
    /// The app that had the keyboard when the hotkey had to activate us; it gets the keyboard
    /// back when the island folds from the keyboard (Escape, the hotkey, the collapse button).
    private var returnTo: NSRunningApplication?
    private var clickMonitor: Any?

    private static let hoverDelay = 0.2
    private static let leaveDelay = 1.0
    private static let peekDuration = 3.2

    init(web: WebIsland) {
        self.web = web
        let screen = IslandGeometry.preferredScreen()
        geometry = screen.map(IslandGeometry.init(screen:))
            ?? IslandGeometry(screen: NSScreen.screens[0])
        panel = IslandPanel(frame: geometry.windowFrame(for: .collapsed))
        view = IslandView(frame: CGRect(origin: .zero, size: geometry.windowFrame(for: .collapsed).size))
        super.init()

        view.delegate = self
        view.autoresizingMask = [.width, .height]
        panel.contentView = view
        panel.onEscape = { [weak self] in self?.escapePressed() }
        view.install(webView: web.webView)
        view.layoutCanvas(geometry)
        placeWindow(for: .collapsed)
        view.setPinned(false)
        applyMode(.collapsed, animated: false)
        renderStatus()
        panel.orderFrontRegardless()

        web.onStatus = { [weak self] in self?.apply(status: $0) }
        web.onLoadState = { [weak self] _ in self?.renderStatus() }
        web.onCollapseRequest = { [weak self] in self?.collapse(force: true) }
        web.onModal = { [weak self] active in
            guard let self else { return }
            self.modalDepth = max(0, self.modalDepth + (active ? 1 : -1))
        }

        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .otherMouseDown]) { [weak self] _ in
            self?.clickedOutside()
        }
        NotificationCenter.default.addObserver(
            self, selector: #selector(screensChanged),
            name: NSApplication.didChangeScreenParametersNotification, object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(didWake),
            name: NSWorkspace.didWakeNotification, object: nil
        )
    }

    // MARK: Public actions

    func expand(makeKey: Bool) {
        if mode != .expanded { applyMode(.expanded, animated: true) }
        if makeKey { panel.makeKey() }
    }

    /// Opens the island with the keyboard in it (hotkey, a click on a notification). `focus`
    /// names the page field for the cursor ("task").
    func openHeld(focus: String?) {
        let wasExpanded = mode == .expanded
        heldOpen = true
        focusOnOpen = focus
        if !wasExpanded { applyMode(.expanded, animated: true) } // tells the page {open, focus}
        focusOnOpen = nil
        takeKeyboard()
        if wasExpanded, let focus { web.focus(focus) }
        evaluatePointer()
    }

    /// Usually the non-activating panel simply becomes key and the app in front stays active.
    /// When that is refused (seen while the app was inactive), activate the app and remember
    /// which app had the keyboard, to give it back when the island folds from the keyboard.
    private func takeKeyboard() {
        panel.makeKey()
        if !panel.isKeyWindow {
            let front = NSWorkspace.shared.frontmostApplication
            if front?.processIdentifier != ProcessInfo.processInfo.processIdentifier { returnTo = front }
            Log.info("activating to take the keyboard")
            NSApp.activate()
            panel.makeKey()
        }
        panel.makeFirstResponder(web.webView)
    }

    /// The global hotkey: open with the cursor in the task row, or fold when it already has the keyboard.
    func toggleFromHotKey() {
        guard modalDepth == 0 else { return } // an alert of ours is open
        if mode == .expanded && panel.isKeyWindow {
            Log.info("hotkey: fold")
            collapse(force: true, returnKeyboard: true)
        } else {
            Log.info("hotkey: open")
            openHeld(focus: "task")
        }
    }

    /// The page can take an approval action right now.
    var isPageReady: Bool {
        web.loadState == .loaded && web.pageSignedIn
    }

    /// Folds the island. `force` also unpins (the collapse button, the page's request).
    /// `returnKeyboard` (folded from the keyboard): if the hotkey had to activate the app, the
    /// app that had the keyboard before gets it back.
    func collapse(force: Bool = false, returnKeyboard: Bool = false) {
        if force { pinned = false }
        guard !pinned, mode != .collapsed else { return }
        let previous = returnTo
        applyMode(.collapsed, animated: true) // forgets returnTo
        guard returnKeyboard, let previous, !previous.isTerminated, NSApp.isActive,
              !hasOtherWindowOpen(), modalDepth == 0 else { return }
        Log.info("keyboard back to the previous app")
        NSApp.yieldActivation(to: previous)
        previous.activate()
    }

    func setPinned(_ value: Bool) {
        pinned = value
        if value {
            expand(makeKey: false)
        } else {
            evaluatePointer()
        }
    }

    func serverChanged() {
        notifier?.serverChanged()
        lastPending = 0
        status = IslandStatus()
        renderStatus()
    }

    func peek() {
        guard mode == .collapsed || mode == .peek else { return }
        Log.info("peek: \(status.pendingApprovals) pending")
        lastPeek = Date()
        if mode == .collapsed { applyMode(.peek, animated: true) }
        view.pulseBadge()
        peekTask?.cancel()
        peekTask = after(Self.peekDuration) { [weak self] in
            guard let self, self.mode == .peek else { return }
            self.applyMode(.collapsed, animated: true)
        }
    }

    // MARK: Status from the page

    private func apply(status new: IslandStatus) {
        let increased = new.signedIn && new.pendingApprovals > lastPending
        lastPending = new.signedIn ? new.pendingApprovals : 0
        let changed = new != status
        status = new
        if changed {
            Log.info("status: pending=\(new.pendingApprovals) active=\(new.activeAgents) signedIn=\(new.signedIn)")
        }
        renderStatus()
        if isPageReady { onPageReady?() }
        guard increased else { return }
        if mode == .peek || (mode == .collapsed && Date().timeIntervalSince(lastPeek) > 4) {
            peek()
        }
    }

    private func renderStatus() {
        let pageReady = web.loadState == .loaded
        let detail: String
        switch web.loadState {
        case .notConfigured: detail = "адрес не задан"
        case .loading: detail = "подключение…"
        case .failed: detail = "нет связи"
        case .loaded:
            if !status.received {
                detail = ""
            } else if !status.signedIn {
                detail = "войдите в moloko"
            } else {
                var parts = [status.activeAgents > 0 ? "агенты работают" : "агенты отдыхают"]
                if status.pendingApprovals > 0 { parts.append("ждут одобрения: \(status.pendingApprovals)") }
                detail = parts.joined(separator: " · ")
            }
        }
        view.render(status: status, pageReady: pageReady, detail: detail)
        view.setLoading(web.loadState == .loading)
        switch web.loadState {
        case .notConfigured:
            view.message.show(
                title: "Адрес moloko не задан",
                detail: "Укажите адрес вашего moloko, например https://имя.ts.net",
                primary: ("Указать адрес…", { [weak self] in self?.onChangeAddress?() })
            )
        case .failed(let reason):
            view.message.show(
                title: "Не удалось открыть moloko",
                detail: "\(reason)\nПовторим автоматически через 20 секунд.",
                primary: ("Повторить", { [weak self] in self?.web.reload() }),
                secondary: ("Сменить адрес…", { [weak self] in self?.onChangeAddress?() })
            )
        case .loading, .loaded:
            view.message.isHidden = true
        }
    }

    // MARK: Mode transitions

    private func applyMode(_ new: IslandMode, animated: Bool) {
        let old = mode
        mode = new
        transitionID += 1
        let id = transitionID
        if new != .peek { peekTask?.cancel() }
        if new != .expanded {
            heldOpen = false
            returnTo = nil
        }
        cancelTimers()

        panel.allowsKey = new == .expanded
        view.interceptsAllClicks = new != .expanded
        if new != .collapsed { placeWindow(for: new) } // grow first; shrink after the animation
        // While folding, the window is still big: let clicks fall through to the apps below.
        panel.ignoresMouseEvents = new == .collapsed && animated
            && panel.frame != geometry.windowFrame(for: .collapsed)

        view.setShape(
            geometry.path(for: new),
            shadowOpacity: new == .expanded ? 0.45 : (new == .peek ? 0.25 : 0),
            animation: animated ? Self.spring(for: new) : nil
        ) { [weak self] in
            guard let self, self.transitionID == id else { return }
            self.finishTransition(to: new)
        }
        view.setContent(for: new, animated: animated)
        view.setHoverRect(geometry.hoverRect(for: new))

        if (old == .expanded) != (new == .expanded) {
            web.setOpen(new == .expanded, focus: new == .expanded ? focusOnOpen : nil)
            Log.info(new == .expanded ? "expanded" : "folded (\(new.rawValue))")
        }
        evaluatePointer()
    }

    private func finishTransition(to mode: IslandMode) {
        guard mode != .expanded else { return }
        view.setWebHidden(true)
        guard mode == .collapsed else { return }
        placeWindow(for: .collapsed)
        panel.ignoresMouseEvents = false
        evaluatePointer() // the pointer may already rest on the pill
    }

    private static func spring(for mode: IslandMode) -> CASpringAnimation {
        let spring: CASpringAnimation
        switch mode {
        case .expanded: spring = CASpringAnimation(perceptualDuration: 0.5, bounce: 0.18)
        case .peek: spring = CASpringAnimation(perceptualDuration: 0.45, bounce: 0.3)
        case .collapsed: spring = CASpringAnimation(perceptualDuration: 0.36, bounce: 0.05)
        }
        spring.duration = spring.settlingDuration
        return spring
    }

    /// The window is just the pill while collapsed, the peek shape while peeking and the whole
    /// canvas while expanded. The canvas itself never moves on screen.
    private func placeWindow(for mode: IslandMode) {
        let frame = geometry.windowFrame(for: mode)
        let giveBackKeyboard = mode == .collapsed && panel.isKeyWindow
        let canvasOrigin = CGPoint(x: geometry.canvasRect.minX - frame.minX, y: geometry.canvasRect.minY - frame.minY)
        if panel.frame != frame || giveBackKeyboard {
            panel.disableScreenUpdatesUntilFlush()
            if giveBackKeyboard { panel.orderOut(nil) } // hands the keyboard back to the active app
            panel.setFrame(frame, display: false)
            view.place(canvasOrigin: canvasOrigin)
            view.displayIfNeeded()
            if giveBackKeyboard { panel.orderFrontRegardless() }
        } else {
            view.place(canvasOrigin: canvasOrigin)
        }
        if mode == .collapsed, NSApp.isActive, !hasOtherWindowOpen(), modalDepth == 0 {
            NSApp.deactivate()
        }
    }

    // MARK: Pointer

    private func pointerInside() -> Bool {
        geometry.toScreen(geometry.hoverRect(for: mode)).contains(NSEvent.mouseLocation)
    }

    private func evaluatePointer() {
        let inside = pointerInside()
        switch mode {
        case .collapsed, .peek:
            leaveTask?.cancel()
            leaveTask = nil
            if inside {
                if hoverTask == nil {
                    hoverTask = after(Self.hoverDelay) { [weak self] in self?.hoverFired() }
                }
            } else {
                hoverTask?.cancel()
                hoverTask = nil
            }
        case .expanded:
            hoverTask?.cancel()
            hoverTask = nil
            if inside || pinned || heldOpen {
                leaveTask?.cancel()
                leaveTask = nil
            } else if leaveTask == nil {
                leaveTask = after(Self.leaveDelay) { [weak self] in self?.leaveFired() }
            }
        }
    }

    private func hoverFired() {
        hoverTask = nil
        guard mode != .expanded, pointerInside() else { return }
        expand(makeKey: false)
    }

    private func leaveFired() {
        leaveTask = nil
        guard mode == .expanded, !pinned, !heldOpen, !pointerInside() else { return }
        // Not while a drag is in flight or an alert is open.
        if modalDepth > 0 || NSEvent.pressedMouseButtons != 0 {
            leaveTask = after(0.5) { [weak self] in self?.leaveFired() }
            return
        }
        collapse()
    }

    private func clickedOutside() {
        guard mode == .expanded, !pinned, modalDepth == 0 else { return }
        collapse()
    }

    private func escapePressed() {
        if mode == .peek {
            applyMode(.collapsed, animated: true)
        } else {
            collapse(returnKeyboard: true)
        }
    }

    private func cancelTimers() {
        hoverTask?.cancel()
        hoverTask = nil
        leaveTask?.cancel()
        leaveTask = nil
    }

    private func after(_ seconds: Double, _ action: @escaping @MainActor () -> Void) -> Task<Void, Never> {
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            action()
        }
    }

    // MARK: IslandViewDelegate

    func islandViewPointerChanged() {
        evaluatePointer()
    }

    func islandViewClicked(atCanvasPoint point: CGPoint) {
        let onIsland = geometry.hoverRect(for: mode).insetBy(dx: -4, dy: -4).contains(point)
        switch mode {
        case .collapsed, .peek:
            if onIsland { expand(makeKey: true) }
        case .expanded:
            if !onIsland { clickedOutside() }
        }
    }

    func islandViewRightClicked(with event: NSEvent) {
        guard geometry.hoverRect(for: mode).contains(view.canvasPoint(of: event)) else { return }
        cancelTimers()
        NSMenu.popUpContextMenu(makeMenu(), with: event, for: view)
        evaluatePointer()
    }

    func islandViewTogglePin() {
        setPinned(!pinned)
    }

    func islandViewCollapse() {
        collapse(force: true, returnKeyboard: true)
    }

    // MARK: Context menu

    private func makeMenu() -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        menu.addItem(item("Обновить", #selector(menuReload)))
        menu.addItem(item("Сменить адрес moloko…", #selector(menuChangeAddress)))
        if let (_, mode) = NotchMode.notchModeAvailable() {
            // The screen is in a "below the notch" mode: the island cannot sit in the notch.
            menu.addItem(item("Показать вырез (экран \(mode.width)×\(mode.height))", #selector(menuShowNotch)))
        }
        menu.addItem(.separator())
        menu.addItem(item(pinned ? "Открепить" : "Закрепить", #selector(menuTogglePin)))
        if let hotKey { menu.addItem(hotKeyMenuItem(hotKey)) }
        if let notifier {
            switch notifier.permission {
            case .denied:
                menu.addItem(item("Уведомления об одобрениях запрещены — открыть Настройки…", #selector(menuNotificationSettings)))
            case .notDetermined:
                menu.addItem(item("Включить уведомления об одобрениях", #selector(menuAskNotifications)))
            case .allowed, .unknown:
                break
            }
            notifier.refreshPermission() // for the next time the menu opens
        }
        let login = item("Запускать при входе", #selector(menuToggleLoginItem))
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)
        menu.addItem(.separator())
        menu.addItem(item("Выйти", #selector(menuQuit)))
        return menu
    }

    private func item(_ title: String, _ action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        return item
    }

    @objc private func menuReload() {
        web.reload()
    }

    @objc private func menuChangeAddress() {
        onChangeAddress?()
    }

    @objc private func menuShowNotch() {
        NotchMode.switchToNotchMode() // the island follows via didChangeScreenParameters
    }

    @objc private func menuTogglePin() {
        setPinned(!pinned)
    }

    @objc private func menuToggleLoginItem() {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled {
                try service.unregister()
            } else {
                try service.register()
                if service.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
            }
            Log.info("login item: \(service.status == .enabled ? "on" : "off")")
        } catch {
            Log.error("login item change failed: \(error.localizedDescription)")
            let alert = NSAlert()
            alert.messageText = "Не удалось изменить автозапуск"
            alert.informativeText = "\(error.localizedDescription)\n\nПереместите приложение в «Программы» и попробуйте снова."
            _ = runAlert(alert)
        }
    }

    @objc private func menuQuit() {
        NSApp.terminate(nil)
    }

    // MARK: Hotkey and notifications

    private func hotKeyMenuItem(_ hotKey: GlobalHotKey) -> NSMenuItem {
        let state = hotKey.state
        let title: String
        switch state {
        case .off: title = "Горячая клавиша: выключена"
        case .active(let combo): title = "Горячая клавиша: \(combo.title)"
        default: title = "Горячая клавиша: \(state.combo?.title ?? "") — занята"
        }
        let parent = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let submenu = NSMenu()
        submenu.autoenablesItems = false
        if let problem = state.problem {
            let note = NSMenuItem(title: problem, action: nil, keyEquivalent: "")
            note.isEnabled = false
            submenu.addItem(note)
            submenu.addItem(.separator())
        }
        for combo in HotKeyCombo.presets {
            let current = state.combo == combo
            // Enabled macOS shortcuts would swallow the keys before us: offered, but disabled.
            let system = !current && GlobalHotKey.systemShortcutUses(combo)
            let choice = item(system ? "\(combo.title) — занято macOS" : combo.title, #selector(menuChooseHotKey(_:)))
            choice.representedObject = combo.id
            choice.state = current ? .on : .off
            choice.isEnabled = !system
            submenu.addItem(choice)
        }
        submenu.addItem(.separator())
        let off = item("Выключить", #selector(menuChooseHotKey(_:)))
        off.representedObject = HotKeyCombo.offID
        off.state = state == .off ? .on : .off
        submenu.addItem(off)
        parent.submenu = submenu
        return parent
    }

    @objc private func menuChooseHotKey(_ sender: NSMenuItem) {
        if let id = sender.representedObject as? String { chooseHotKey(id: id) }
    }

    /// Switches the hotkey to a preset (or off); a combination that is taken keeps the old one.
    func chooseHotKey(id: String) {
        guard let hotKey else { return }
        let previous = hotKey.state.combo
        let combo = HotKeyCombo.preset(id: id)
        let state = hotKey.register(combo)
        if combo == nil || state.isActive {
            AppSettings.shared.hotKeyID = id
            return
        }
        hotKey.register(previous) // keep what worked before
        showAlert(
            title: "Это сочетание занято",
            text: "\(state.problem ?? "") Выберите другое сочетание."
        )
    }

    /// The saved hotkey could not be registered at launch: tell the owner once per launch.
    func reportHotKeyProblem(_ state: GlobalHotKey.State) {
        guard let problem = state.problem else { return }
        let alert = NSAlert()
        alert.messageText = "Горячая клавиша островка не работает"
        alert.informativeText = "\(problem)\n\nВыберите другое сочетание: правый щелчок по островку → «Горячая клавиша»."
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Выключить горячую клавишу")
        if runAlert(alert) == .alertSecondButtonReturn {
            hotKey?.register(nil)
            AppSettings.shared.hotKeyID = HotKeyCombo.offID
        }
    }

    @objc private func menuNotificationSettings() {
        notifier?.openSettings()
    }

    @objc private func menuAskNotifications() {
        notifier?.askPermission()
    }

    private func showAlert(title: String, text: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        alert.addButton(withTitle: "OK")
        _ = runAlert(alert)
    }

    private func runAlert(_ alert: NSAlert) -> NSApplication.ModalResponse {
        modalDepth += 1
        NSApp.activate()
        let response = alert.runModal()
        modalDepth -= 1
        if mode != .expanded, !hasOtherWindowOpen() { NSApp.deactivate() }
        return response
    }

    // MARK: Environment

    @objc private func screensChanged() {
        guard let screen = IslandGeometry.preferredScreen() else { return }
        let next = IslandGeometry(screen: screen)
        guard next.canvasRect != geometry.canvasRect || next.collapsedSize != geometry.collapsedSize else { return }
        Log.info("screen changed; re-laying out")
        geometry = next
        pinned = false
        view.layoutCanvas(geometry)
        applyMode(.collapsed, animated: false) // also re-places the window for the new screen
    }

    @objc private func didWake() {
        if case .failed = web.loadState { web.reload() }
    }

    // MARK: Debug (MOLOKO_ISLAND_DEBUG only)

    var debugState: String {
        "mode=\(mode.rawValue) pinned=\(pinned) key=\(panel.isKeyWindow) ignoresMouse=\(panel.ignoresMouseEvents) frame=\(panel.frame) mouse=\(NSEvent.mouseLocation) "
            + "webVisible=\(view.isWebVisible) load=\(web.loadState) status=\(status) notch=\(geometry.hasNotch) "
            + "collapsed=\(geometry.collapsedSize) expanded=\(geometry.expandedSize) held=\(heldOpen) "
            + "active=\(NSApp.isActive) front=\(NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "-") pageReady=\(isPageReady) hotKey=\(hotKey.map { "\($0.state)" } ?? "none")"
    }

    /// The context menu as text: one line per item, submenus indented.
    var debugMenu: String {
        func lines(_ menu: NSMenu, _ indent: String) -> [String] {
            menu.items.flatMap { item -> [String] in
                if item.isSeparatorItem { return [indent + "---"] }
                let mark = item.state == .on ? "✓ " : ""
                let off = item.isEnabled ? "" : " (disabled)"
                return [indent + mark + item.title + off] + (item.submenu.map { lines($0, indent + "    ") } ?? [])
            }
        }
        return lines(makeMenu(), "").joined(separator: " | ")
    }

    func debugSnapshot(to path: String) {
        let write: (NSImage?) -> Void = { [weak self] image in
            guard let self, let data = self.view.debugSnapshot(webImage: image) else {
                Log.error("snapshot failed")
                return
            }
            do {
                try data.write(to: URL(fileURLWithPath: path))
                Log.info("snapshot written: \(path)")
            } catch {
                Log.error("snapshot write failed: \(error.localizedDescription)")
            }
        }
        if view.isWebVisible {
            web.webView.takeSnapshot(with: nil) { image, _ in write(image) }
        } else {
            write(nil)
        }
    }
}
