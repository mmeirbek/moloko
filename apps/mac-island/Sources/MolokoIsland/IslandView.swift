import AppKit

@MainActor
protocol IslandViewDelegate: AnyObject {
    func islandViewPointerChanged()
    func islandViewClicked(atCanvasPoint point: CGPoint)
    func islandViewRightClicked(with event: NSEvent)
    func islandViewTogglePin()
    func islandViewCollapse()
}

/// What the island shows; filled by the controller from the page's bridge messages.
struct IslandStatus: Equatable {
    var pendingApprovals = 0
    var activeAgents = 0
    var signedIn = false
    /// At least one `status` message arrived from the current page.
    var received = false
}

/// The panel's content view.
///
/// Layers: `backdrop` draws the black island shape (with shadow); `content` holds every
/// control and the web view and is masked by the same shape. Both cover the whole canvas
/// even when the window is only as big as the collapsed pill — the window frame changes,
/// the canvas never moves on screen.
final class IslandView: NSView {
    weak var delegate: IslandViewDelegate?

    private let backdrop = NSView()
    private let backgroundLayer = CAShapeLayer()
    private let content = NSView()
    private let maskLayer = CAShapeLayer()

    // Collapsed pill
    private let collapsedGroup = NSView()
    private let pillDot = StatusDotView()
    private let pillBadge = BadgeView()
    private let pillTitle = NSTextField(labelWithString: "moloko")
    private let peekLabel = NSTextField(labelWithString: "")

    // Expanded panel
    private let header = NSView()
    private let headerDot = StatusDotView()
    private let headerTitle = NSTextField(labelWithString: "moloko")
    private let headerDetail = NSTextField(labelWithString: "")
    private lazy var pinButton = IslandButton.symbol("pin", tooltip: "Закрепить", target: self, action: #selector(pinPressed))
    private lazy var collapseButton = IslandButton.symbol("chevron.up", tooltip: "Свернуть", target: self, action: #selector(collapsePressed))
    let webHolder = NSView()
    let message = MessageView()
    private let spinner = NSProgressIndicator()

    /// While not expanded, every click on the island belongs to the island itself.
    var interceptsAllClicks = true
    private var hoverCanvasRect: CGRect = .zero
    private var canvasSize: CGSize = .zero
    private var expandedRect: CGRect = .zero

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true

        backdrop.layer = CALayer() // layer-hosting: we own its sublayers
        backdrop.wantsLayer = true
        backgroundLayer.fillColor = NSColor.black.cgColor
        backgroundLayer.shadowColor = NSColor.black.cgColor
        backgroundLayer.shadowOpacity = 0
        backgroundLayer.shadowRadius = 14
        backgroundLayer.shadowOffset = CGSize(width: 0, height: -4)
        backdrop.layer?.addSublayer(backgroundLayer)
        addSubview(backdrop)

        content.wantsLayer = true
        maskLayer.fillColor = NSColor.black.cgColor
        content.layer?.mask = maskLayer
        addSubview(content)

        for label in [pillTitle, peekLabel, headerTitle, headerDetail] {
            label.isSelectable = false
            label.lineBreakMode = .byTruncatingTail
        }
        pillTitle.font = .systemFont(ofSize: 11, weight: .semibold)
        pillTitle.textColor = IslandColors.secondaryText
        pillTitle.alignment = .center
        peekLabel.font = .systemFont(ofSize: 12, weight: .semibold)
        peekLabel.textColor = IslandColors.amber
        peekLabel.alignment = .center
        headerTitle.font = .systemFont(ofSize: 13, weight: .semibold)
        headerTitle.textColor = IslandColors.text
        headerDetail.font = .systemFont(ofSize: 12)
        headerDetail.textColor = IslandColors.secondaryText

        collapsedGroup.addSubview(pillDot)
        collapsedGroup.addSubview(pillTitle)
        collapsedGroup.addSubview(pillBadge)
        content.addSubview(collapsedGroup)
        content.addSubview(peekLabel)

        header.addSubview(headerDot)
        header.addSubview(headerTitle)
        header.addSubview(headerDetail)
        header.addSubview(pinButton)
        header.addSubview(collapseButton)
        content.addSubview(header)

        webHolder.wantsLayer = true
        webHolder.layer?.cornerRadius = 14
        webHolder.layer?.masksToBounds = true
        webHolder.layer?.backgroundColor = IslandColors.surface.cgColor
        message.isHidden = true
        message.autoresizingMask = [.width, .height]
        webHolder.addSubview(message)
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isDisplayedWhenStopped = false
        spinner.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin, .maxYMargin]
        webHolder.addSubview(spinner)
        content.addSubview(webHolder)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // MARK: Layout

    func install(webView: NSView) {
        webView.frame = webHolder.bounds
        webView.autoresizingMask = [.width, .height]
        webHolder.addSubview(webView, positioned: .below, relativeTo: message)
    }

    /// Lays out everything inside the canvas for one screen.
    func layoutCanvas(_ g: IslandGeometry) {
        canvasSize = g.canvasRect.size
        let pill = g.rect(for: .collapsed)
        collapsedGroup.frame = pill
        let ear = IslandGeometry.earWidth
        if g.hasNotch {
            pillDot.frame = CGRect(x: 0, y: 0, width: ear, height: pill.height)
            pillBadge.frame = CGRect(x: pill.width - ear, y: 0, width: ear, height: pill.height)
            pillTitle.isHidden = true
        } else {
            pillDot.frame = CGRect(x: 6, y: 0, width: 26, height: pill.height)
            pillBadge.frame = CGRect(x: pill.width - 42, y: 0, width: 38, height: pill.height)
            pillTitle.isHidden = false
            let titleHeight = pillTitle.intrinsicContentSize.height
            pillTitle.frame = CGRect(x: 34, y: (pill.height - titleHeight) / 2, width: pill.width - 68, height: titleHeight)
        }

        let peek = g.rect(for: .peek)
        peekLabel.frame = CGRect(x: peek.minX + 12, y: peek.minY + 7, width: peek.width - 24, height: 18)

        let expanded = g.rect(for: .expanded)
        expandedRect = expanded
        let headerHeight = g.headerHeight
        header.frame = CGRect(x: expanded.minX, y: expanded.maxY - headerHeight, width: expanded.width, height: headerHeight)
        let midY = headerHeight / 2
        headerDot.frame = CGRect(x: 14, y: midY - 9, width: 18, height: 18)
        let titleSize = headerTitle.intrinsicContentSize
        headerTitle.frame = CGRect(x: 34, y: midY - titleSize.height / 2, width: ceil(titleSize.width) + 8, height: titleSize.height)
        let detailX = headerTitle.frame.maxX + 8
        // On a notched screen the middle of the header is hidden behind the notch.
        let detailLimit = g.hasNotch ? (expanded.width - g.notchWidth) / 2 - 8 : expanded.width - 90
        let detailHeight = headerDetail.intrinsicContentSize.height
        headerDetail.frame = CGRect(x: detailX, y: midY - detailHeight / 2, width: max(0, detailLimit - detailX), height: detailHeight)
        collapseButton.frame = CGRect(x: expanded.width - 40, y: midY - 12, width: 26, height: 24)
        pinButton.frame = CGRect(x: expanded.width - 68, y: midY - 12, width: 26, height: 24)

        webHolder.frame = CGRect(
            x: expanded.minX + 8,
            y: expanded.minY + 8,
            width: expanded.width - 16,
            height: expanded.height - headerHeight - 8
        )
        message.frame = webHolder.bounds
        spinner.sizeToFit()
        spinner.frame.origin = CGPoint(
            x: (webHolder.bounds.width - spinner.frame.width) / 2,
            y: (webHolder.bounds.height - spinner.frame.height) / 2
        )
    }

    /// Places the canvas inside the window (its origin in window coordinates).
    func place(canvasOrigin: CGPoint) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        let frame = CGRect(origin: canvasOrigin, size: canvasSize)
        backdrop.frame = frame
        content.frame = frame
        backgroundLayer.frame = backdrop.bounds
        maskLayer.frame = content.bounds
        updateScale()
        CATransaction.commit()
        updateTrackingAreas()
    }

    override func viewDidChangeBackingProperties() {
        super.viewDidChangeBackingProperties()
        updateScale()
    }

    private func updateScale() {
        let scale = window?.backingScaleFactor ?? NSScreen.main?.backingScaleFactor ?? 2
        backgroundLayer.contentsScale = scale
        maskLayer.contentsScale = scale
    }

    // MARK: Shape and content state

    /// Morphs the island outline (spring when `animation` is given).
    func setShape(
        _ path: CGPath, shadowOpacity: Float, animation: CASpringAnimation?,
        completion: @escaping () -> Void
    ) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        CATransaction.setCompletionBlock(completion)
        morph(backgroundLayer, keyPath: "path", to: path, animation: animation)
        morph(backgroundLayer, keyPath: "shadowPath", to: path, animation: animation)
        morph(maskLayer, keyPath: "path", to: path, animation: animation)

        let fromOpacity = backgroundLayer.presentation()?.shadowOpacity ?? backgroundLayer.shadowOpacity
        backgroundLayer.shadowOpacity = shadowOpacity
        if animation != nil {
            let fade = CABasicAnimation(keyPath: "shadowOpacity")
            fade.fromValue = fromOpacity
            fade.toValue = shadowOpacity
            fade.duration = 0.3
            backgroundLayer.add(fade, forKey: "shadowOpacity")
        }
        CATransaction.commit()
    }

    private func morph(_ layer: CAShapeLayer, keyPath: String, to path: CGPath, animation: CASpringAnimation?) {
        let current: CGPath? = keyPath == "path"
            ? (layer.presentation()?.path ?? layer.path)
            : (layer.presentation()?.shadowPath ?? layer.shadowPath)
        layer.removeAnimation(forKey: keyPath)
        if keyPath == "path" { layer.path = path } else { layer.shadowPath = path }
        guard let animation, let current, let spring = animation.copy() as? CASpringAnimation else { return }
        spring.keyPath = keyPath
        spring.fromValue = current
        spring.toValue = path
        layer.add(spring, forKey: keyPath)
    }

    func setContent(for mode: IslandMode, animated: Bool) {
        let targets: [(NSView, CGFloat)] = [
            (collapsedGroup, mode == .expanded ? 0 : 1),
            (peekLabel, mode == .peek ? 1 : 0),
            (header, mode == .expanded ? 1 : 0),
            (webHolder, mode == .expanded ? 1 : 0),
        ]
        if mode == .expanded { webHolder.isHidden = false }
        guard animated else {
            targets.forEach { $0.0.alphaValue = $0.1 }
            return
        }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = mode == .expanded ? 0.3 : 0.14
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            targets.forEach { $0.0.animator().alphaValue = $0.1 }
        }
    }

    /// Hidden while collapsed: WebKit then treats the page as hidden (no rendering, timers
    /// throttled) but keeps the page and its realtime connection alive.
    func setWebHidden(_ hidden: Bool) {
        webHolder.isHidden = hidden
    }

    var isWebVisible: Bool { !webHolder.isHidden && webHolder.alphaValue > 0 }

    func setHoverRect(_ rect: CGRect) {
        hoverCanvasRect = rect
        updateTrackingAreas()
    }

    // MARK: Status

    func render(status: IslandStatus, pageReady: Bool, detail: String) {
        let style: StatusDotView.Style
        if !pageReady || !status.signedIn {
            style = .offline
        } else {
            style = status.activeAgents > 0 ? .working : .idle
        }
        pillDot.style = style
        headerDot.style = style
        pillBadge.count = status.signedIn ? status.pendingApprovals : 0
        peekLabel.stringValue = Self.pendingText(status.pendingApprovals)
        headerDetail.stringValue = detail
    }

    func setPinned(_ pinned: Bool) {
        pinButton.image = NSImage(systemSymbolName: pinned ? "pin.fill" : "pin", accessibilityDescription: nil)
        pinButton.contentTintColor = pinned ? IslandColors.amber : IslandColors.secondaryText
        pinButton.toolTip = pinned ? "Открепить" : "Закрепить"
    }

    func setLoading(_ loading: Bool) {
        if loading { spinner.startAnimation(nil) } else { spinner.stopAnimation(nil) }
    }

    func pulseBadge() {
        pillBadge.pulse()
    }

    static func pendingText(_ n: Int) -> String {
        let mod10 = n % 10, mod100 = n % 100
        if mod10 == 1 && mod100 != 11 { return "\(n) действие ждёт одобрения" }
        if (2...4).contains(mod10) && !(12...14).contains(mod100) { return "\(n) действия ждут одобрения" }
        return "\(n) действий ждут одобрения"
    }

    // MARK: Mouse

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        let rect = hoverCanvasRect.offsetBy(dx: content.frame.minX, dy: content.frame.minY)
        guard !rect.isEmpty else { return }
        var options: NSTrackingArea.Options = [.mouseEnteredAndExited, .activeAlways]
        if let window, rect.contains(convert(window.mouseLocationOutsideOfEventStream, from: nil)) {
            options.insert(.assumeInside)
        }
        addTrackingArea(NSTrackingArea(rect: rect, options: options, owner: self))
    }

    override func mouseEntered(with event: NSEvent) { delegate?.islandViewPointerChanged() }
    override func mouseExited(with event: NSEvent) { delegate?.islandViewPointerChanged() }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard let hit = super.hitTest(point) else { return nil }
        if interceptsAllClicks { return self }
        // Web content and buttons handle their own clicks; the rest of the island is ours.
        if hit is NSButton || hit.isDescendant(of: webHolder) { return hit }
        return self
    }

    func canvasPoint(of event: NSEvent) -> CGPoint {
        content.convert(event.locationInWindow, from: nil)
    }

    override func mouseDown(with event: NSEvent) {
        delegate?.islandViewClicked(atCanvasPoint: canvasPoint(of: event))
    }

    override func rightMouseDown(with event: NSEvent) {
        delegate?.islandViewRightClicked(with: event)
    }

    @objc private func pinPressed() { delegate?.islandViewTogglePin() }
    @objc private func collapsePressed() { delegate?.islandViewCollapse() }

    // MARK: Debug snapshot (MOLOKO_ISLAND_DEBUG only)

    /// Draws the island the way it is composed on screen: used to check the layout without
    /// Screen Recording permission. `webImage` is `WKWebView.takeSnapshot` of the page.
    func debugSnapshot(webImage: NSImage?) -> Data? {
        let size = content.bounds.size
        let scale: CGFloat = 2
        guard size.width > 0, size.height > 0,
              let space = CGColorSpace(name: CGColorSpace.sRGB),
              let cg = CGContext(
                  data: nil, width: Int(size.width * scale), height: Int(size.height * scale),
                  bitsPerComponent: 8, bytesPerRow: 0, space: space,
                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
              ) else { return nil }
        cg.scaleBy(x: scale, y: scale)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: cg, flipped: false)
        NSColor(srgbRed: 0.82, green: 0.86, blue: 0.92, alpha: 1).setFill() // stand-in for the desktop
        CGRect(origin: .zero, size: size).fill()
        if let path = backgroundLayer.path {
            cg.addPath(path)
            cg.setFillColor(NSColor.black.cgColor)
            cg.fillPath()
            cg.addPath(path)
            cg.clip()
        }
        // The whole tree in one pass, so flipped subviews (text fields) compose as on screen.
        // CALayer.render skips masked layers; the clip above already does the masking.
        content.displayIfNeeded()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        let mask = content.layer?.mask
        content.layer?.mask = nil
        content.layer?.render(in: cg)
        content.layer?.mask = mask
        CATransaction.commit()
        // WebKit's remote layers are not rendered by CALayer.render: paint the page snapshot.
        if isWebVisible, message.isHidden, let webImage {
            NSBezierPath(roundedRect: webHolder.frame, xRadius: 14, yRadius: 14).addClip()
            webImage.draw(in: webHolder.frame)
        }
        NSGraphicsContext.restoreGraphicsState()
        guard let image = cg.makeImage() else { return nil }
        return NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])
    }

}
