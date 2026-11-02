import AppKit

@main
@MainActor
enum MolokoIslandMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory) // no Dock icon (LSUIElement in the bundle too)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let web = WebIsland()
    private let setup = SetupWindowController()
    private var controller: IslandController?
    private var debug: DebugCommands?

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMainMenu()
        let controller = IslandController(web: web)
        self.controller = controller
        controller.onChangeAddress = { [weak self] in self?.showSetup(firstRun: false) }
        controller.hasOtherWindowOpen = { [weak self] in self?.setup.isVisible ?? false }

        setup.onSave = { [weak self] url in self?.useServer(url) }
        setup.onQuit = { NSApp.terminate(nil) }
        setup.onClose = { [weak self] in
            guard let self, self.controller?.mode != .expanded else { return }
            NSApp.deactivate()
        }

        // MOLOKO_ISLAND_SERVER=<address> overrides the saved address for this run only (development).
        let override = ProcessInfo.processInfo.environment["MOLOKO_ISLAND_SERVER"].flatMap(ServerAddress.normalize)
        let server = override ?? AppSettings.shared.serverURL
        web.load(server: server)
        if server == nil { showSetup(firstRun: true) }
        if Log.debugEnabled { debug = DebugCommands(controller: controller, setup: setup) }
        Log.info("started, version \(AppInfo.version), server \(override != nil ? "from MOLOKO_ISLAND_SERVER" : (server == nil ? "not set" : "set"))")
    }

    private func showSetup(firstRun: Bool) {
        setup.show(current: AppSettings.shared.serverURL, firstRun: firstRun)
    }

    private func useServer(_ url: URL) {
        AppSettings.shared.serverURL = url
        Log.info("server address saved")
        controller?.serverChanged()
        web.load(server: url)
        controller?.expand(makeKey: true) // show the page right away (it may ask to log in)
    }

    /// LSUIElement apps have no visible menu bar, but copy/paste shortcuts in the web view and
    /// the address field still go through the main menu's key equivalents. Deliberately no
    /// ⌘Q/⌘H: they would quit/hide the island when it merely holds the keyboard focus.
    private func installMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        appItem.submenu = NSMenu()
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Правка")
        edit.addItem(withTitle: "Отменить", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Повторить", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Вырезать", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Скопировать", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Вставить", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Выбрать всё", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)
        NSApp.mainMenu = main
    }
}
