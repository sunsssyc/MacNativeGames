"""Bake native gestures on the rounded-mouth rig, preserving previous actions."""
import sys,math,bisect,json
from pathlib import Path
import bpy
from mathutils import Matrix,Vector,Euler
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--parser',type=Path,required=True,help='Directory containing bfrespy')
parser.add_argument('--assets',type=Path,required=True,help='Local game-decoded and game-original directories')
parser.add_argument('--scene',type=Path,required=True,help='Rounded-mouth rig with existing gesture actions')
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--only',help='Bake only these comma-separated native actions')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
ROOT=args.assets;OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(args.parser))
from bfrespy.res_file import ResFile
from bfrespy.skeletal_anim import BoneAnimFlagsBase as Base
from bfrespy.common import AnimCurveType as Curve
def load(p):
 with p.open('rb') as f:return ResFile(f)
load(ROOT/'game-decoded/ExternalBinaryString.bfres')
model=next(iter(load(ROOT/'game-decoded/Npc_Gerudo_Queen_Young.Npc_Gerudo_Queen_Young.bfres').models.values()))
clips={}
for archive in ['Npc_Gerudo_Queen_Young_Soul_Animation.anim.bfres','Npc_Gerudo_Queen_Young_Combat_Soul_Animation.anim.bfres']:
 clips.update(dict(load(ROOT/'game-original'/archive).skeletal_anims.items()))
def evaluate(c,f):
 i=max(0,min(len(c.frames)-1,bisect.bisect_right(c.frames,f)-1));k=c.keys[i]
 t=0 if i==len(c.frames)-1 else max(0,min(1,(f-c.frames[i])/(c.frames[i+1]-c.frames[i])))
 v=k[0]+t*(k[1]+t*(k[2]+t*k[3])) if c.curve_type==Curve.CUBIC else k[0]+t*k[1] if c.curve_type==Curve.LINEAR else k[0]
 return v*(c.scale if c.scale else 1)+c.offs
def local(b,ba,f):
 s=list(b.scale);r=list(b.rotation);p=list(b.position)
 if ba:
  if ba.base_data:
   if ba.flags_base & Base.SCALE:s=list(ba.base_data.scale)
   if ba.flags_base & Base.ROTATE:r=list(ba.base_data.rotate)
   if ba.flags_base & Base.TRANSLATE:p=list(ba.base_data.translate)
  for c in ba.curves:
   off=c.anim_data_offset
   if 4<=off<=12:s[(off-4)//4]=evaluate(c,f)
   elif 32<=off<=44:r[(off-32)//4]=evaluate(c,f)
   elif 16<=off<=24:p[(off-16)//4]=evaluate(c,f)
 return Matrix.LocRotScale(Vector(p),Euler(r[:3],'XYZ'),Vector(s))
bpy.ops.wm.open_mainfile(filepath=str(args.scene))
scene=bpy.context.scene;arm=next(o for o in scene.objects if o.type=='ARMATURE')
bones=list(model.skeleton.bones.values());rest={b.name:local(b,None,0) for b in bones}
selected=['Default_Move_Walk','Common_Move_Run','Combat_Wait','Combat_Move_Run','Jump_St','Jump','Jump_Ed']
if args.only:selected=args.only.split(',')
stats=[]
for name in selected:
 a=clips[name];bamap={b.name:b for b in a.bone_anims}
 act=bpy.data.actions.new(name);act.use_fake_user=True;arm.animation_data.action=act
 for frame in range(a.frame_cnt+1):
  for b in bones:
   pb=arm.pose.bones[b.name];pb.rotation_mode='QUATERNION';pb.matrix_basis=rest[b.name].inverted()@local(b,bamap.get(b.name),frame)
   for channel in ('location','rotation_quaternion','scale'):pb.keyframe_insert(channel,frame=frame+1,group=b.name)
 stats.append({'name':name,'frames':a.frame_cnt,'bones':len(a.bone_anims)})
 print('BAKED',name,flush=True)
arm.animation_data.action=bpy.data.actions['Default_Wait'];scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'riju-companion-actions.blend'))
(OUT/'baked-actions.json').write_text(json.dumps(stats,indent=2))
