import AppKit
import WebKit

/// The first click goes straight to the page even while the panel is not key
/// (otherwise "approve" would need two clicks after a hover-expand).
final class IslandWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// Owns the web view that shows `<server>/island` and the JS bridge with that page.
///
/// Bridge contract (page → native), via `window.webkit.messageHandlers.molokoIsland.postMessage`:
///   { type: "status", pendingApprovals: number, activeAgents: number, signedIn: boolean }
///   { type: "openExternal", url: string }   // open in the default browser (http/https/mailto)
///   { type: "collapse" }                    // fold the island (also when pinned)
///   { type: "approval", id, summary, agent }  // a pending approval the page has not reported yet
///   { type: "approvalGone", id }              // a reported approval is no longer pending
///   { type: "approvalsPending", ids: [id] }   // once per page load: every pending approval
///   { type: "approvalResolved", id, ok, message }  // the answer to an `action` event below
/// Native → page:
///   window.molokoIsland = { native: true, version: string, open: boolean }  (from document start)
///   window.dispatchEvent(new CustomEvent("moloko-island", { detail }))  where detail is
///     { open }                         on every open/close and once after each page load,
///     { open: true, focus: "task" }    opened from the hotkey: put the cursor in the task row,
///     { action: "approve" | "reject", approvalId }  a notification button: answer that approval.
/// Messages are accepted only from the main frame of the configured moloko host.
@MainActor
final class WebIsland: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    enum LoadState: Equatable {
        case notConfigured
        case loading
        case loaded
        case failed(String)
    }

    let webView: IslandWebView
    private(set) var baseURL: URL?
    private(set) var loadState: LoadState = .notConfigured {
        didSet { if loadState != oldValue { onLoadState?(loadState) } }
    }

    var onStatus: ((IslandStatus) -> Void)?
    var onLoadState: ((LoadState) -> Void)?
    var onCollapseRequest: (() -> Void)?
    var onApproval: ((_ id: String, _ summary: String, _ agent: String) -> Void)?
    var onApprovalGone: ((_ id: String) -> Void)?
    var onApprovalsPending: ((_ ids: [String]) -> Void)?
    var onApprovalResolved: ((_ id: String, _ ok: Bool, _ message: String) -> Void)?
    /// Called around native alert/confirm/open panels so the island does not fold meanwhile.
    var onModal: ((Bool) -> Void)?

    /// The current document said it is signed in (its bridge listens for actions).
    private(set) var pageSignedIn = false
    private var isOpen = false
    private var retryTask: Task<Void, Never>?

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default() // persistent cookies: log in once
        configuration.applicationNameForUserAgent = "MolokoIsland/\(AppInfo.version)"
        configuration.preferences.inactiveSchedulingPolicy = .throttle // never suspend the page
        webView = IslandWebView(frame: CGRect(x: 0, y: 0, width: 800, height: 560), configuration: configuration)
        super.init()
        configuration.userContentController.add(WeakScriptHandler(self), name: AppInfo.bridgeName)
        installUserScripts()
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsMagnification = false
        webView.isInspectable = true // Safari ▸ Develop ▸ Moloko Island
        webView.underPageBackgroundColor = .black
        if webView.responds(to: NSSelectorFromString("setDrawsBackground:")) {
            webView.setValue(false, forKey: "drawsBackground") // no white flash before the page paints
        }
    }

    // MARK: Loading

    func load(server: URL?) {
        retryTask?.cancel()
        baseURL = server
        guard let server else {
            loadState = .notConfigured
            webView.loadHTMLString("", baseURL: nil)
            return
        }
        loadState = .loading
        Log.info("loading \(server.absoluteString)/island")
        webView.load(URLRequest(url: server.appendingPathComponent("island")))
    }

    func reload() {
        switch loadState {
        case .loaded where webView.url != nil:
            webView.reload()
        default:
            load(server: baseURL)
        }
    }

    private func scheduleRetry() {
        retryTask?.cancel()
        retryTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 20_000_000_000)
            guard !Task.isCancelled, let self, case .failed = self.loadState else { return }
            self.load(server: self.baseURL)
        }
    }

    // MARK: Native → page

    /// `focus` ("task") asks the page to put the cursor into that field once it is visible.
    func setOpen(_ open: Bool, focus: String? = nil) {
        isOpen = open
        installUserScripts() // so a page loaded later starts with the right `open`
        dispatchOpenState(focus: focus)
    }

    /// The panel is already open: only move the cursor (hotkey while hover-expanded).
    func focus(_ field: String) {
        dispatchOpenState(focus: field)
    }

    /// A notification button: the page answers the approval with its session and CSRF token.
    func sendApprovalAction(_ action: String, approvalId: String) {
        guard ["approve", "reject"].contains(action), ApprovalNotifier.isValidID(approvalId) else { return }
        dispatch(detail: "{ action: \(Self.jsString(action)), approvalId: \(Self.jsString(approvalId)) }")
    }

    private func dispatchOpenState(focus: String? = nil) {
        let focusPart = focus.map { ", focus: \(Self.jsString($0))" } ?? ""
        dispatch(detail: "{ open: \(isOpen)\(focusPart) }")
    }

    private func dispatch(detail: String) {
        let script = stateScript
            + "window.dispatchEvent(new CustomEvent(\(Self.jsString(AppInfo.eventName)), { detail: \(detail) }));"
        webView.evaluateJavaScript(script, completionHandler: nil)
    }

    private var stateScript: String {
        "window.molokoIsland = Object.assign(window.molokoIsland || {}, { native: true, version: \(Self.jsString(AppInfo.version)), open: \(isOpen) });"
    }

    private func installUserScripts() {
        let controller = webView.configuration.userContentController
        controller.removeAllUserScripts()
        controller.addUserScript(WKUserScript(source: stateScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        controller.addUserScript(WKUserScript(source: Self.linkScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }

    /// Client-side routers (Next.js `<Link>`) change the URL without a real navigation, so the
    /// navigation policy below never sees them. This capture-phase listener sends every link
    /// that leaves `/island` and `/login` (or has target=_blank) to the default browser.
    private static let linkScript = """
    (function () {
      if (window.__molokoIslandLinks) return;
      window.__molokoIslandLinks = true;
      document.addEventListener("click", function (event) {
        if (event.button !== 0 || event.defaultPrevented) return;
        var target = event.target;
        var anchor = target && target.closest ? target.closest("a[href]") : null;
        if (!anchor || anchor.hasAttribute("download")) return;
        var url;
        try { url = new URL(anchor.getAttribute("href"), location.href); } catch (e) { return; }
        if (url.protocol !== "http:" && url.protocol !== "https:") return;
        var inside = url.host === location.host && /^\\/(island|login)(\\/|$)/.test(url.pathname);
        if (inside && anchor.target !== "_blank") return;
        event.preventDefault();
        event.stopImmediatePropagation();
        window.webkit.messageHandlers.\(AppInfo.bridgeName).postMessage({ type: "openExternal", url: url.href });
      }, true);
    })();
    """

    private static func jsString(_ value: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed),
              let text = String(data: data, encoding: .utf8) else { return "\"\"" }
        return text
    }

    // MARK: Page → native

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, isTrusted(message.frameInfo.securityOrigin) else {
            Log.error("bridge message from an untrusted origin ignored")
            return
        }
        guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "status":
            var status = IslandStatus()
            status.pendingApprovals = Self.count(body["pendingApprovals"])
            status.activeAgents = Self.count(body["activeAgents"])
            status.signedIn = (body["signedIn"] as? Bool) ?? false
            status.received = true
            pageSignedIn = status.signedIn
            onStatus?(status)
        case "openExternal":
            if let text = body["url"] as? String, let url = URL(string: text, relativeTo: webView.url)?.absoluteURL {
                openExternally(url)
            }
        case "collapse":
            onCollapseRequest?()
        case "approval":
            guard let id = body["id"] as? String else { return }
            onApproval?(id, (body["summary"] as? String) ?? "", (body["agent"] as? String) ?? "")
        case "approvalGone":
            if let id = body["id"] as? String { onApprovalGone?(id) }
        case "approvalsPending":
            let ids = (body["ids"] as? [Any])?.compactMap { $0 as? String } ?? []
            onApprovalsPending?(ids)
        case "approvalResolved":
            guard let id = body["id"] as? String else { return }
            onApprovalResolved?(id, (body["ok"] as? Bool) ?? false, (body["message"] as? String) ?? "")
        default:
            Log.info("unknown bridge message type ignored")
        }
    }

    private static func count(_ value: Any?) -> Int {
        guard let number = value as? NSNumber else { return 0 }
        let double = number.doubleValue
        guard double.isFinite, double > 0 else { return 0 }
        return Int(min(double, 9_999))
    }

    private func isTrusted(_ origin: WKSecurityOrigin) -> Bool {
        guard let host = baseURL?.host?.lowercased() else { return false }
        return (origin.protocol == "http" || origin.protocol == "https") && origin.host.lowercased() == host
    }

    private func isOnServer(_ url: URL) -> Bool {
        guard let host = baseURL?.host?.lowercased() else { return false }
        return url.host?.lowercased() == host
    }

    /// `/island…` and `/login…` stay inside the island; everything else goes to the browser.
    private func staysInside(_ url: URL) -> Bool {
        guard isOnServer(url) else { return false }
        let path = url.path.isEmpty ? "/" : url.path
        return ["/island", "/login"].contains { path == $0 || path.hasPrefix($0 + "/") }
    }

    private func openExternally(_ url: URL) {
        guard let scheme = url.scheme?.lowercased(), ["http", "https", "mailto"].contains(scheme) else {
            Log.error("refused to open a non-web link")
            return
        }
        Log.info("opening in the default browser: \(url.host ?? scheme)")
        NSWorkspace.shared.open(url)
    }

    // MARK: WKNavigationDelegate

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url, let scheme = url.scheme?.lowercased() else {
            decisionHandler(.cancel)
            return
        }
        if ["about", "blob", "data"].contains(scheme) {
            decisionHandler(.allow)
            return
        }
        guard scheme == "http" || scheme == "https" else {
            if navigationAction.navigationType == .linkActivated { openExternally(url) }
            decisionHandler(.cancel)
            return
        }
        guard let frame = navigationAction.targetFrame else { // target=_blank / window.open
            openExternally(url)
            decisionHandler(.cancel)
            return
        }
        if !frame.isMainFrame || staysInside(url) {
            decisionHandler(.allow)
            return
        }
        openExternally(url)
        decisionHandler(.cancel)
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping @MainActor (WKNavigationResponsePolicy) -> Void
    ) {
        if navigationResponse.isForMainFrame, let http = navigationResponse.response as? HTTPURLResponse,
           http.statusCode >= 500 {
            loadState = .failed("Сервер ответил \(http.statusCode).")
            scheduleRetry()
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        if baseURL != nil, loadState != .loaded { loadState = .loading }
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        pageSignedIn = false // a new document: wait for its own status message
        if baseURL != nil { loadState = .loaded }
        if let url = webView.url, isOnServer(url), url.path == "/login" || url.path.hasPrefix("/login/") {
            // The login page does not talk to the bridge: we know we are signed out.
            onStatus?(IslandStatus(pendingApprovals: 0, activeAgents: 0, signedIn: false, received: true))
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if baseURL != nil { loadState = .loaded }
        dispatchOpenState()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handleFailure(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        let nsError = error as NSError
        Log.error("page load interrupted: \(nsError.domain) \(nsError.code)")
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        Log.error("web content process ended; reloading")
        load(server: baseURL)
    }

    private func handleFailure(_ error: Error) {
        let nsError = error as NSError
        // Cancelled on purpose: our own policy decisions or a newer navigation.
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled { return }
        if nsError.domain == "WebKitErrorDomain" && (nsError.code == 102 || nsError.code == 204) { return }
        guard baseURL != nil else { return }
        Log.error("cannot open moloko: \(nsError.domain) \(nsError.code)")
        loadState = .failed(nsError.localizedDescription)
        scheduleRetry()
    }

    // MARK: WKUIDelegate

    /// Voice input in the island: the microphone only, and only for the moloko server's own page.
    func webView(
        _ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
        initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
        decisionHandler: @escaping @MainActor (WKPermissionDecision) -> Void
    ) {
        let ours = frame.isMainFrame && origin.host == baseURL?.host
        decisionHandler(ours && type == .microphone ? .grant : .deny)
    }

    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url { openExternally(url) }
        return nil
    }

    func webView(
        _ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor () -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        _ = runModal(alert)
        completionHandler()
    }

    func webView(
        _ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor (Bool) -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Отмена")
        completionHandler(runModal(alert) == .alertFirstButtonReturn)
    }

    func webView(
        _ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
        defaultText: String?, initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor (String?) -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = prompt
        let field = NSTextField(frame: CGRect(x: 0, y: 0, width: 260, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Отмена")
        completionHandler(runModal(alert) == .alertFirstButtonReturn ? field.stringValue : nil)
    }

    func webView(
        _ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        onModal?(true)
        NSApp.activate()
        let response = panel.runModal()
        onModal?(false)
        completionHandler(response == .OK ? panel.urls : nil)
    }

    private func runModal(_ alert: NSAlert) -> NSApplication.ModalResponse {
        onModal?(true)
        NSApp.activate()
        let response = alert.runModal()
        onModal?(false)
        return response
    }
}

/// Breaks the retain cycle WKUserContentController → handler.
private final class WeakScriptHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?

    init(_ target: WKScriptMessageHandler) {
        self.target = target
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(userContentController, didReceive: message)
    }
}
