"""
    ESSArch is an open source archiving and digital preservation system

    ESSArch Tools for Producer (ETP)
    Copyright (C) 2005-2017 ES Solutions AB

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

    Contact information:
    Web - http://www.essolutions.se
    Email - essarch@essolutions.se
"""

import os
import shutil

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TransactionTestCase

from ESSArch_Core.configuration.models import (
    EventType, Path,
)

from ESSArch_Core.ip.models import (
    EventIP, InformationPackage,
)

from ESSArch_Core.WorkflowEngine.models import (
    ProcessTask,
)


class test_tasks(TransactionTestCase):
    def setUp(self):
        settings.CELERY_ALWAYS_EAGER = True
        settings.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True

        self.root = os.path.dirname(os.path.realpath(__file__))
        self.prepare_path = os.path.join(self.root, "prepare")
        self.preingest_reception = os.path.join(self.root, "preingest_reception")
        self.ingest_reception = os.path.join(self.root, "ingest_reception")

        for path in [self.prepare_path, self.preingest_reception, self.ingest_reception]:
            try:
                os.makedirs(path)
            except OSError as e:
                if e.errno != 17:
                    raise

        Path.objects.create(
            entity="path_preingest_prepare",
            value=self.prepare_path
        )
        Path.objects.create(
            entity="path_preingest_reception",
            value=self.preingest_reception
        )
        Path.objects.create(
            entity="path_ingest_reception",
            value=self.ingest_reception
        )

    def tearDown(self):
        for path in [self.prepare_path, self.preingest_reception, self.ingest_reception]:
            try:
                shutil.rmtree(path)
            except:
                pass

    def test_prepare_ip(self):
        label = "ip1"
        user = User.objects.create(username="user1")
        event_type = EventType.objects.create(eventType=10100)

        task = ProcessTask.objects.create(
            name="preingest.tasks.PrepareIP",
            params={
                "label": label,
                "responsible": str(user.pk)
            },
            responsible=user
        )
        task.run()

        ip = InformationPackage.objects.filter(label=label).first()

        self.assertIsNotNone(ip)

        self.assertTrue(
            EventIP.objects.filter(
                linkingObjectIdentifierValue=ip,
                eventOutcome=0,
                linkingAgentIdentifierValue=user,
                eventType=event_type,
            ).exists()
        )

        task.undo()

        self.assertFalse(
            InformationPackage.objects.filter(label=label).exists()
        )

    def test_create_ip_root_dir(self):
        ip = InformationPackage.objects.create(label="ip1")
        user = User.objects.create(username="user1")
        prepare_path = Path.objects.get(entity="path_preingest_prepare").value
        prepare_path = os.path.join(prepare_path, unicode(ip.pk))
        event_type = EventType.objects.create(eventType=10110)

        task = ProcessTask.objects.create(
            name="preingest.tasks.CreateIPRootDir",
            params={
                "information_package": ip.pk,
            },
            responsible=user
        )
        task.run()

        self.assertTrue(
            os.path.isdir(prepare_path)
        )

        self.assertTrue(
            EventIP.objects.filter(
                linkingObjectIdentifierValue=ip,
                eventOutcome=0,
                linkingAgentIdentifierValue=user,
                eventType=event_type,
            ).exists()
        )

        task.undo()

        self.assertFalse(
            os.path.isdir(prepare_path)
        )

    def test_create_physical_model(self):
        ip = InformationPackage.objects.create(label="ip1")
        prepare_path = Path.objects.get(entity="path_preingest_prepare").value
        path = os.path.join(prepare_path, unicode(ip.pk))

        task = ProcessTask.objects.create(
            name="preingest.tasks.CreatePhysicalModel",
            params={
                "structure": [
                    {
                        "name": "dir1",
                        "type": "folder"
                    },
                    {
                        "name": "dir2",
                        "type": "folder",
                    },
                    {
                        "name": "file1",
                        "type": "file"
                    }
                ]
            },
            information_package=ip,
        )
        task.run()

        self.assertTrue(
            os.path.isdir(os.path.join(path, 'dir1'))
        )
        self.assertTrue(
            os.path.isdir(os.path.join(path, 'dir2'))
        )
        self.assertFalse(
            os.path.isfile(os.path.join(path, 'file1'))
        )

        task.undo()

        self.assertFalse(
            os.path.isdir(os.path.join(path, 'dir1'))
        )
        self.assertFalse(
            os.path.isdir(os.path.join(path, 'dir2'))
        )

    def test_submit_sip(self):
        ip = InformationPackage.objects.create(label="ip1")

        srctar = os.path.join(self.preingest_reception, "%s.tar" % ip.pk)
        srcxml = os.path.join(self.preingest_reception, "%s.xml" % ip.pk)
        dsttar = os.path.join(self.ingest_reception, "%s.tar" % ip.pk)
        dstxml = os.path.join(self.ingest_reception, "%s.xml" % ip.pk)
        open(srctar, "a").close()
        open(srcxml, "a").close()

        task = ProcessTask.objects.create(
            name="preingest.tasks.SubmitSIP",
            params={
                "ip": ip.pk
            },
        )
        task.run()

        self.assertTrue(os.path.isfile(dsttar))
        self.assertTrue(os.path.isfile(dstxml))

        task.undo()

        self.assertFalse(os.path.isfile(dsttar))
        self.assertFalse(os.path.isfile(dstxml))
