import Foundation
import CoreGraphics
import ImageIO
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let manifest=try JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("manifest.json"))) as! [String:Any]
let clips=manifest["clips"] as! [String:[String:Any]]
var checked=0,minMargin=192
for (name,clip) in clips {
 let count=clip["frames"] as! Int
 let w=clip["width"] as? Int ?? (manifest["width"] as! Int), h=manifest["height"] as! Int
 for i in 0..<count {
  let url=root.appendingPathComponent(name).appendingPathComponent(String(format:"%03d.png",i))
  let src=CGImageSourceCreateWithURL(url as CFURL,nil)!
  let image=CGImageSourceCreateImageAtIndex(src,0,nil)!
  precondition(image.width==w && image.height==h)
  let ctx=CGContext(data:nil,width:w,height:h,bitsPerComponent:8,bytesPerRow:w*4,space:CGColorSpace(name:CGColorSpace.sRGB)!,bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
  ctx.draw(image,in:CGRect(x:0,y:0,width:w,height:h))
  let p=ctx.data!.assumingMemoryBound(to:UInt8.self)
  var visible=0
  for y in 0..<h {for x in 0..<w {
   if p[(y*w+x)*4+3]>128 {
    visible+=1;minMargin=min(minMargin,x,w-1-x,y,h-1-y)
    precondition(x>1 && x<w-2 && y>1 && y<h-2,"Clipped pose: \(name) \(i)")
   }
  }}
  precondition(visible>1000,"Empty pose: \(name) \(i)");checked+=1
 }
}
print("Validated \(checked) nonempty transparent frames, minimum edge clearance \(minMargin) px")
