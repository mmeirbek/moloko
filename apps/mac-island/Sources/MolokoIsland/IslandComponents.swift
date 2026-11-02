import AppKit

enum IslandColors {
    static let amber = NSColor(srgbRed: 1.0, green: 0.69, blue: 0.13, alpha: 1)
    static let green = NSColor(srgbRed: 0.20, green: 0.84, blue: 0.42, alpha: 1)
    static let grey = NSColor(white: 0.56, alpha: 1)
    static let text = NSColor(white: 0.94, alpha: 1)
    static let secondaryText = NSColor(white: 0.62, alpha: 1)
    static let surface = NSColor(white: 0.07, alpha: 1)
}

/// Green = agents working, grey = idle, grey ring = no data (not signed in / no connection).
final class StatusDotView: NSView {
    enum Style { case working, idle, offline }

    var style: Style = .offline {
        didSet {
            guard style != oldValue else { return }
            needsDisplay = true
            updatePulse()
        }
    }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func draw(_ dirtyRect: NSRect) {
        let size: CGFloat = 8
        let dot = CGRect(x: bounds.midX - size / 2, y: bounds.midY - size / 2, width: size, height: size)
        switch style {
        case .working:
            IslandColors.green.withAlphaComponent(0.28).setFill()
            NSBezierPath(ovalIn: dot.insetBy(dx: -2.5, dy: -2.5)).fill()
            IslandColors.green.setFill()
            NSBezierPath(ovalIn: dot).fill()
        case .idle:
            IslandColors.grey.setFill()
            NSBezierPath(ovalIn: dot).fill()
        case .offline:
            let ring = NSBezierPath(ovalIn: dot.insetBy(dx: 0.75, dy: 0.75))
            ring.lineWidth = 1.5
            IslandColors.grey.withAlphaComponent(0.8).setStroke()
            ring.stroke()
        }
    }

    private func updatePulse() {
        guard let layer else { return }
        if style == .working {
            guard layer.animation(forKey: "pulse") == nil else { return }
            let pulse = CABasicAnimation(keyPath: "opacity")
            pulse.fromValue = 1.0
            pulse.toValue = 0.45
            pulse.duration = 0.9
            pulse.autoreverses = true
            pulse.repeatCount = .infinity
            pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            layer.add(pulse, forKey: "pulse")
        } else {
            layer.removeAnimation(forKey: "pulse")
        }
    }
}

/// Amber capsule with the number of pending approvals; hidden at zero.
final class BadgeView: NSView {
    var count = 0 {
        didSet {
            guard count != oldValue else { return }
            isHidden = count <= 0
            needsDisplay = true
        }
    }

    private var text: String { count > 99 ? "99+" : "\(count)" }

    private var attributes: [NSAttributedString.Key: Any] {
        [.font: NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .bold), .foregroundColor: NSColor.black]
    }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        isHidden = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func draw(_ dirtyRect: NSRect) {
        let textSize = (text as NSString).size(withAttributes: attributes)
        let height: CGFloat = 18
        let width = max(height, ceil(textSize.width) + 10)
        let capsule = CGRect(x: bounds.midX - width / 2, y: bounds.midY - height / 2, width: width, height: height)
        IslandColors.amber.setFill()
        NSBezierPath(roundedRect: capsule, xRadius: height / 2, yRadius: height / 2).fill()
        (text as NSString).draw(
            at: CGPoint(x: capsule.midX - textSize.width / 2, y: capsule.midY - textSize.height / 2),
            withAttributes: attributes
        )
    }

    /// A short bounce so a new approval request is noticed.
    func pulse() {
        guard let layer, !isHidden else { return }
        let w = bounds.width / 2, h = bounds.height / 2 // the layer's anchor is its corner on macOS
        func scaled(_ s: CGFloat) -> NSValue {
            var t = CATransform3DMakeTranslation(w, h, 0)
            t = CATransform3DScale(t, s, s, 1)
            t = CATransform3DTranslate(t, -w, -h, 0)
            return NSValue(caTransform3D: t)
        }
        let bounce = CAKeyframeAnimation(keyPath: "transform")
        bounce.values = [scaled(1), scaled(1.35), scaled(1), scaled(1.25), scaled(1), scaled(1.15), scaled(1)]
        bounce.duration = 1.4
        bounce.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        layer.add(bounce, forKey: "pulse")
    }
}

/// Buttons react to the first click even though the panel is not key.
final class IslandButton: NSButton {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    static func symbol(_ name: String, tooltip: String, target: AnyObject, action: Selector) -> IslandButton {
        let image = NSImage(systemSymbolName: name, accessibilityDescription: tooltip) ?? NSImage()
        let button = IslandButton(image: image, target: target, action: action)
        button.isBordered = false
        button.bezelStyle = .accessoryBarAction
        button.imagePosition = .imageOnly
        button.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold)
        button.contentTintColor = IslandColors.secondaryText
        button.toolTip = tooltip
        button.setAccessibilityLabel(tooltip)
        return button
    }
}

/// Native message over the web area: address not set, server unreachable, …
final class MessageView: NSView {
    private let titleLabel = NSTextField(labelWithString: "")
    private let detailLabel = NSTextField(wrappingLabelWithString: "")
    private let primaryButton = IslandButton(title: "", target: nil, action: nil)
    private let secondaryButton = IslandButton(title: "", target: nil, action: nil)
    private var onPrimary: (() -> Void)?
    private var onSecondary: (() -> Void)?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        titleLabel.font = .systemFont(ofSize: 15, weight: .semibold)
        titleLabel.textColor = IslandColors.text
        titleLabel.alignment = .center
        detailLabel.font = .systemFont(ofSize: 12)
        detailLabel.textColor = IslandColors.secondaryText
        detailLabel.alignment = .center
        detailLabel.preferredMaxLayoutWidth = 420
        for button in [primaryButton, secondaryButton] {
            button.bezelStyle = .rounded
            button.controlSize = .regular
            button.target = self
        }
        primaryButton.action = #selector(primaryPressed)
        secondaryButton.action = #selector(secondaryPressed)
        primaryButton.keyEquivalent = "\r"

        let buttons = NSStackView(views: [secondaryButton, primaryButton])
        buttons.orientation = .horizontal
        buttons.spacing = 10
        let stack = NSStackView(views: [titleLabel, detailLabel, buttons])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 10
        stack.setCustomSpacing(16, after: detailLabel)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: widthAnchor, constant: -40),
        ])
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func draw(_ dirtyRect: NSRect) {
        IslandColors.surface.setFill()
        bounds.fill()
    }

    func show(
        title: String, detail: String,
        primary: (String, () -> Void)?, secondary: (String, () -> Void)? = nil
    ) {
        titleLabel.stringValue = title
        detailLabel.stringValue = detail
        detailLabel.isHidden = detail.isEmpty
        primaryButton.title = primary?.0 ?? ""
        primaryButton.isHidden = primary == nil
        onPrimary = primary?.1
        secondaryButton.title = secondary?.0 ?? ""
        secondaryButton.isHidden = secondary == nil
        onSecondary = secondary?.1
        isHidden = false
    }

    @objc private func primaryPressed() { onPrimary?() }
    @objc private func secondaryPressed() { onSecondary?() }
}
