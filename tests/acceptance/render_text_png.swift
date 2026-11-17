// Render a UTF-8 text file into a PNG for local OCR acceptance (no network).
// usage: swift render_text_png.swift <input.txt> <output.png>
import Foundation
import AppKit

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write("usage: render_text_png.swift <input.txt> <output.png>\n".data(using: .utf8)!)
    exit(2)
}
let text = try String(contentsOfFile: args[1], encoding: .utf8)
let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
let fontSize: CGFloat = 28
let lineHeight: CGFloat = 44
let width: CGFloat = 1200
let height: CGFloat = CGFloat(max(1, lines.count)) * lineHeight + 40
let font = NSFont.systemFont(ofSize: fontSize)
let attributed = lines.map { line in
    NSAttributedString(string: line, attributes: [.font: font, .foregroundColor: NSColor.black])
}
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width), pixelsHigh: Int(height),
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSColor.white.set()
NSRect(x: 0, y: 0, width: width, height: height).fill()
var y = height - lineHeight
for line in attributed {
    line.draw(in: NSRect(x: 24, y: y, width: width - 48, height: lineHeight))
    y -= lineHeight
}
NSGraphicsContext.restoreGraphicsState()
guard let data = rep.representation(using: .png, properties: [:]) else {
    FileHandle.standardError.write("png encode failed\n".data(using: .utf8)!)
    exit(2)
}
try data.write(to: URL(fileURLWithPath: args[2]))
