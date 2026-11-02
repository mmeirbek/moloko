import AppKit

enum IslandMode: String {
    case collapsed, peek, expanded
}

/// All sizes of the island for one screen.
///
/// The island is drawn inside a fixed "canvas" hanging from the top centre of the screen
/// (big enough for the expanded panel plus room for the shadow and the spring overshoot).
/// Shape rects are in canvas coordinates (AppKit style: origin bottom-left, y up), and the
/// top edge of every shape is the top edge of the screen.
///
/// Notch geometry: on MacBooks with a notch, `safeAreaInsets.top` is the notch height and
/// the notch width is what `auxiliaryTopLeftArea`/`auxiliaryTopRightArea` leave free.
struct IslandGeometry {
    static let earWidth: CGFloat = 38 // visible part of the pill on each side of the notch
    static let canvasMargin: CGFloat = 28
    static let preferredExpanded = CGSize(width: 820, height: 600) // office map at 100% + header + agents row

    let screenFrame: CGRect
    let hasNotch: Bool
    let notchWidth: CGFloat
    /// Height of the collapsed pill: the notch height, or the menu bar height without a notch.
    let barHeight: CGFloat
    let headerHeight: CGFloat
    let collapsedSize: CGSize
    let peekSize: CGSize
    let expandedSize: CGSize
    /// The canvas in screen coordinates.
    let canvasRect: CGRect

    init(screen: NSScreen) {
        screenFrame = screen.frame
        var notch: CGFloat = 0
        var notchHeight: CGFloat = 0
        if screen.safeAreaInsets.top > 0,
           let left = screen.auxiliaryTopLeftArea, let right = screen.auxiliaryTopRightArea {
            notch = screen.frame.width - left.width - right.width
            notchHeight = screen.safeAreaInsets.top
        }
        hasNotch = notch > 40 && notchHeight > 0
        notchWidth = hasNotch ? notch : 0

        let menuBar = screen.frame.maxY - screen.visibleFrame.maxY
        if hasNotch {
            barHeight = notchHeight
        } else {
            // The menu bar may be auto-hidden (then visibleFrame reaches the top).
            barHeight = (18...44).contains(menuBar) ? menuBar : 28
        }
        headerHeight = max(barHeight, 30)

        let collapsedWidth = hasNotch ? notchWidth + 2 * Self.earWidth : 148
        collapsedSize = CGSize(width: collapsedWidth, height: barHeight)
        peekSize = CGSize(width: max(collapsedWidth + 48, 280), height: barHeight + 30)

        let width = min(Self.preferredExpanded.width, screen.frame.width - 32)
        let height = min(Self.preferredExpanded.height, screen.frame.height - 60)
        expandedSize = CGSize(
            width: max(width, collapsedWidth + 40).rounded(),
            height: max(height, headerHeight + 160).rounded()
        )

        let canvasWidth = expandedSize.width + 2 * Self.canvasMargin
        let canvasHeight = expandedSize.height + Self.canvasMargin
        canvasRect = CGRect(
            x: (screenFrame.midX - canvasWidth / 2).rounded(),
            y: screenFrame.maxY - canvasHeight,
            width: canvasWidth,
            height: canvasHeight
        )
    }

    func size(for mode: IslandMode) -> CGSize {
        switch mode {
        case .collapsed: collapsedSize
        case .peek: peekSize
        case .expanded: expandedSize
        }
    }

    /// The island body (without the concave shoulders) in canvas coordinates.
    func rect(for mode: IslandMode) -> CGRect {
        let size = size(for: mode)
        return CGRect(
            x: (canvasRect.width - size.width) / 2,
            y: canvasRect.height - size.height,
            width: size.width,
            height: size.height
        )
    }

    func bottomRadius(for mode: IslandMode) -> CGFloat {
        switch mode {
        case .collapsed: hasNotch ? 10 : min(12, barHeight / 2)
        case .peek: 16
        case .expanded: 22
        }
    }

    func shoulder(for mode: IslandMode) -> CGFloat {
        switch mode {
        case .collapsed: 6
        case .peek: 8
        case .expanded: 10
        }
    }

    func path(for mode: IslandMode) -> CGPath {
        Self.islandPath(rect: rect(for: mode), bottomRadius: bottomRadius(for: mode), shoulder: shoulder(for: mode))
    }

    /// Area that counts as "the pointer is on the island" (canvas coordinates).
    func hoverRect(for mode: IslandMode) -> CGRect {
        let body = rect(for: mode)
        switch mode {
        case .collapsed, .peek:
            return body.insetBy(dx: -shoulder(for: mode), dy: 0)
        case .expanded:
            return body.insetBy(dx: -6, dy: -6)
        }
    }

    func toScreen(_ canvasRectValue: CGRect) -> CGRect {
        canvasRectValue.offsetBy(dx: canvasRect.minX, dy: canvasRect.minY)
    }

    /// Window frame for a mode: the pill (collapsed) or the peek shape (plus room for the
    /// spring overshoot) — so the transparent canvas never sits over other apps and swallows
    /// their clicks — or the whole canvas while expanded.
    func windowFrame(for mode: IslandMode) -> CGRect {
        let body = toScreen(rect(for: mode))
        let shoulder = shoulder(for: mode)
        switch mode {
        case .collapsed:
            return CGRect(
                x: floor(body.minX - shoulder - 1),
                y: body.minY,
                width: ceil(body.width + 2 * shoulder + 2),
                height: body.height
            )
        case .peek:
            let room: CGFloat = 16
            return CGRect(
                x: floor(body.minX - shoulder - room),
                y: floor(body.minY - room),
                width: ceil(body.width + 2 * (shoulder + room)),
                height: ceil(body.height + room)
            )
        case .expanded:
            return canvasRect
        }
    }

    /// Black island outline: flat top on the screen edge, small concave "shoulders" that melt
    /// into the screen edge, rounded bottom corners. Every outline has the same elements in
    /// the same order, so Core Animation can interpolate between any two of them.
    static func islandPath(rect: CGRect, bottomRadius: CGFloat, shoulder: CGFloat) -> CGPath {
        let k: CGFloat = 0.5523 // cubic Bézier approximation of a quarter circle
        let radius = min(bottomRadius, rect.height / 2, rect.width / 2)
        let left = rect.minX, right = rect.maxX, top = rect.maxY, bottom = rect.minY
        let path = CGMutablePath()
        path.move(to: CGPoint(x: left - shoulder, y: top))
        path.addCurve(
            to: CGPoint(x: left, y: top - shoulder),
            control1: CGPoint(x: left - shoulder * (1 - k), y: top),
            control2: CGPoint(x: left, y: top - shoulder * (1 - k))
        )
        path.addLine(to: CGPoint(x: left, y: bottom + radius))
        path.addCurve(
            to: CGPoint(x: left + radius, y: bottom),
            control1: CGPoint(x: left, y: bottom + radius * (1 - k)),
            control2: CGPoint(x: left + radius * (1 - k), y: bottom)
        )
        path.addLine(to: CGPoint(x: right - radius, y: bottom))
        path.addCurve(
            to: CGPoint(x: right, y: bottom + radius),
            control1: CGPoint(x: right - radius * (1 - k), y: bottom),
            control2: CGPoint(x: right, y: bottom + radius * (1 - k))
        )
        path.addLine(to: CGPoint(x: right, y: top - shoulder))
        path.addCurve(
            to: CGPoint(x: right + shoulder, y: top),
            control1: CGPoint(x: right, y: top - shoulder * (1 - k)),
            control2: CGPoint(x: right + shoulder * (1 - k), y: top)
        )
        path.closeSubpath()
        return path
    }

    /// The screen with a notch (the built-in display) if there is one, else the menu bar screen.
    static func preferredScreen() -> NSScreen? {
        NSScreen.screens.first { $0.safeAreaInsets.top > 0 && $0.auxiliaryTopLeftArea != nil }
            ?? NSScreen.screens.first
    }
}
