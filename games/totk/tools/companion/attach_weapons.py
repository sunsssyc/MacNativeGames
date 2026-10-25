"""Attach Riju's native twin scimitars rigidly to Weapon_L / Weapon_R.

Read only locally extracted user game assets. The weapon importer converts Y-up
vertices to Blender Z-up; undo that once, then apply the character bone's rest
matrix. An armature modifier follows the bone head (not Blender's bone tail).
"""
import argparse, sys, math
from pathlib import Path
import bpy
from mathutils import Matrix
p=argparse.ArgumentParser()
p.add_argument('--assets',type=Path,required=True)
p.add_argument('--scene',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
sys.path.insert(0,str(a.assets/'BlenderBfresImporter'))
sys.path.insert(0,str(a.assets))
from io_scene_bfres.bfrespy.res_file import ResFile
from io_scene_bfres.mesh_importer import import_mesh
from io_scene_bfres.skeleton_importer import import_fskl
from original_textures import texture
bpy.ops.wm.open_mainfile(filepath=str(a.scene))
s=bpy.context.scene;arm=next(o for o in s.objects if o.type=='ARMATURE')
with (a.assets/'game-decoded/ExternalBinaryString.bfres').open('rb') as f:ResFile(f)
with (a.assets/'weapon-decoded/Weapon_Sword_052.Weapon_Sword_052.bfres').open('rb') as f:r=ResFile(f)
model=next(iter(r.models.values()))
temporary=import_fskl(model,model.skeleton,s.collection,False)
materials=[]
for mat in model.materials.values():
 m=bpy.data.materials.new('Scimitar_'+mat.name);m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=.4;bs.inputs['Metallic'].default_value=.25
 alb=a.assets/'weapon-source/Weapon_Sword_052_Dm_Alb.txtg'
 node=m.node_tree.nodes.new('ShaderNodeTexImage');node.image=texture(alb)
 m.node_tree.links.new(node.outputs['Color'],bs.inputs['Base Color'])
 materials.append(m)
for side in ('L','R'):
 bone='Weapon_'+side
 for shape in model.shapes.values():
  # Keep the detachable *_Blade_Hide shape: the name is a fuse visibility
  # group; the base shape alone contains only the handle and guard.
  ob=import_mesh(model,shape,0,True);s.collection.objects.link(ob)
  ob.name='CompanionScimitar_'+side+'_'+shape.name;ob['companion_weapon']=True
  transform=arm.data.bones[bone].matrix_local @ Matrix.Scale(.50,4) @ Matrix.Rotation(-math.pi/2,4,'X')
  ob.data.transform(transform)
  ob.vertex_groups.clear();g=ob.vertex_groups.new(name=bone);g.add(list(range(len(ob.data.vertices))),1,'REPLACE')
  ob.parent=arm;ob.matrix_parent_inverse=Matrix.Identity(4);ob.matrix_basis=Matrix.Identity(4)
  mod=ob.modifiers.new('Rigid weapon socket','ARMATURE');mod.object=arm
  ob.data.materials.clear();ob.data.materials.append(materials[shape.material_idx])
  print('ATTACHED',ob.name,bone,len(ob.data.vertices),flush=True)
bpy.data.objects.remove(temporary,do_unlink=True)
arm.animation_data.action=bpy.data.actions['Combat_Wait'];s.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(a.output))
s.render.resolution_x=576;s.render.resolution_y=864;s.render.resolution_percentage=100
s.render.filepath=str(a.output.parent/'armed-preview.png');bpy.ops.render.render(write_still=True)
