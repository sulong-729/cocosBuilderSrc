import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import Builder

class IncrementalTests(unittest.TestCase):
    def test_compatibility_second_pass_preserves_files_and_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);creator=root/'Creator.app/Contents/MacOS/CocosCreator'
            lib=creator.parent.parent/'Resources/resources/3d/engine/native/external/ios/libs/libwebp.a'
            lib.parent.mkdir(parents=True);lib.write_bytes(b'original')
            project=root/'Project.xcodeproj';project.mkdir();pbx=project/'project.pbxproj'
            pbx.write_text('OTHER_LDFLAGS = ("/old/libwebp.a");')
            out=root/'output';out.mkdir();builder=Builder(lambda _:None,lambda _:None)
            calls=[]
            def run(args,cwd):
                calls.append(args)
                Path(args[-1]).write_bytes(b'fixed')
            with patch.object(builder,'run',side_effect=run):
                builder.compatibility(project,creator,out,'x86_64')
                stamp=pbx.stat().st_mtime_ns
                builder.compatibility(project,creator,out,'x86_64')
                self.assertEqual(len(calls),2,'Second pass must reuse library without lipo/libtool')
                self.assertEqual(pbx.stat().st_mtime_ns,stamp,'Unchanged project must not be rewritten')
                builder.compatibility(project,creator,out,'arm64')
                self.assertEqual(len(calls),4,'Changing architecture must rebuild library')
