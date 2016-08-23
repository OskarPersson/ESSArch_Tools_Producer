from __future__ import unicode_literals

import importlib
import uuid

from celery import chain, group, states as celery_states

from django.db import models
from django.db.models import Sum
from django.utils.translation import ugettext as _

from picklefield.fields import PickledObjectField

from preingest.managers import StepManager
from preingest.util import available_tasks, sliceUntilAttr


class ArchiveObject(models.Model):

    CHECKSUM_ALGORITHM_CHOICES = (
        ('md5', 'MD5'),
        ('sha1', 'SHA-1'),
        ('sha224', 'SHA-224'),
        ('sha256', 'SHA-256'),
        ('sha384', 'SHA-384'),
        ('sha512', 'SHA-512')
    )

    ObjectUUID = models.UUIDField(primary_key=True, default=uuid.uuid4,
                                  editable=False)
    label = models.CharField(max_length=255)
    filesize = models.IntegerField(null=True)
    checksum = models.CharField(max_length=255, null=True)
    checksum_algorithm = models.CharField(choices=CHECKSUM_ALGORITHM_CHOICES,
            max_length=255, null=True)

    class Meta:
        db_table = u'ArchiveObject'

    def __unicode__(self):
        return self.label

class Process(models.Model):
    class Meta:
        abstract = True

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result = PickledObjectField(null=True, default=None, editable=False)

    def __unicode__(self):
        return self.name

class ProcessStep(Process):
    Type_CHOICES = (
        (0, "Receive new object"),
        (5, "The object is ready to remodel"),
        (9, "New object stable"),
        (10, "Object don't exist in AIS"),
        (11, "Object don't have any projectcode in AIS"),
        (12, "Object don't have any local policy"),
        (13, "Object already have an AIP!"),
        (14, "Object is not active!"),
        (19, "Object got a policy"),
        (20, "Object not updated from AIS"),
        (21, "Object not accepted in AIS"),
        (24, "Object accepted in AIS"),
        (25, "SIP validate"),
        (30, "Create AIP package"),
        (40, "Create package checksum"),
        (50, "AIP validate"),
        (60, "Try to remove IngestObject"),
        (1000, "Write AIP to longterm storage"),
        (1500, "Remote AIP"),
        (2009, "Remove temp AIP object OK"),
        (3000, "Archived"),
        (5000, "ControlArea"),
        (5100, "WorkArea"),
        (9999, "Deleted"),
    )

    name = models.CharField(max_length=256)
    type = models.IntegerField(null=True, choices=Type_CHOICES)
    user = models.CharField(max_length=45)
    parent_step = models.ForeignKey('self', related_name='child_steps', on_delete=models.CASCADE, null=True)
    time_created = models.DateTimeField(auto_now_add=True)
    archiveobject = models.ForeignKey('ArchiveObject', related_name='steps', blank=True, null=True)
    hidden = models.BooleanField(default=False)
    waitForParams = models.BooleanField(default=False)
    parallel = models.BooleanField(default=False)

    objects = StepManager()

    def _create_task(self, name):
        [module, task] = name.rsplit('.', 1)
        return getattr(importlib.import_module(module), task)()

    def _create_taskobj(self, task, attempt=None, undo=False, retry=False):
        if undo:
            task.undone = undo

        if retry:
            task.retried = retry

        task.save()

        taskobj = ProcessTask(
            processstep=self,
            name=task.name+" undo" if undo else task.name,
            processstep_pos=task.processstep_pos,
            undo_type=undo,
            params=task.params,
            attempt=attempt,
            status="PREPARED"
        )

        taskobj.save()
        return taskobj

    def task_set(self):
        tasks = self.tasks.filter(
            undo_type=False,
            retried=False
        ).order_by("processstep_pos")

        return [t for t in tasks.values("name", "params")]

    def run(self, continuing=False, direct=True):
        """
        Runs the process step

        Args:
            continuing: True if continuing a step that was waiting for params,
                        false otherwise
            direct: False if the step is called from a parent step,
                    true otherwise
        """


        child_steps = self.child_steps.all()

        if continuing:
            child_steps = [s for s in self.child_steps.all() if s.progress() < 100]

        child_steps = sliceUntilAttr(child_steps, "waitForParams", True)

        func = group if self.parallel else chain

        func(s.run(direct=False) for s in child_steps)()

        c = func(self._create_task(t.name).si(
            taskobj=t
        ) for t in self.tasks.all())

        return c() if direct else c

    def undo(self, only_failed=False):
        child_steps = self.child_steps.all()
        tasks = self.tasks.all()

        for c in child_steps:
            c.undo(only_failed=only_failed)

        if only_failed:
            tasks = tasks.filter(status=celery_states.FAILURE)

        tasks = tasks.filter(
            undo_type=False,
            undone=False
        )

        attempt = uuid.uuid4()

        func = group if self.parallel else chain

        func(self._create_task(t.name).si(
            taskobj=self._create_taskobj(t, attempt=attempt, undo=True),
            undo=True
        ) for t in reversed(tasks))()

    def retry(self, direct=True):
        child_steps = sliceUntilAttr(self.child_steps.all(), "waitForParams", True)
        tasks = self.tasks.filter(
            undone=True,
            retried=False
        ).order_by('processstep_pos')

        func = group if self.parallel else chain

        func(c.retry(direct=False) for c in child_steps)()

        attempt = uuid.uuid4()

        c = func(self._create_task(t.name).si(
            taskobj=self._create_taskobj(t, attempt=attempt, retry=True),
        ) for t in tasks)

        return c() if direct else c

    def progress(self):
        child_steps = self.child_steps.all()

        if child_steps:
            try:
                progress = sum([c.progress() for c in child_steps])
                return progress / len(child_steps)
            except:
                return 0

        tasks = self.tasks.filter(
            undone=False,
            undo_type=False,
            retried=False
        )

        if not tasks:
            return 0

        progress = tasks.aggregate(Sum("progress"))["progress__sum"]
        try:
            return progress / len(self.task_set())
        except:
            return 0

    def status(self):
        child_steps = self.child_steps.all()
        tasks = self.tasks.filter(undo_type=False, undone=False, retried=False)

        if not child_steps and not tasks:
            return celery_states.PENDING

        for c in child_steps:
            if c.status() in (celery_states.FAILURE, celery_states.PENDING):
                return c.status()

        for t in tasks:
            if t.status in (celery_states.FAILURE, celery_states.PENDING):
                return t.status

        return celery_states.SUCCESS

    class Meta:
        db_table = u'ProcessStep'

        def __unicode__(self):
            return '%s - %s - archiveobject:%s' % (self.name, self.id, self.archiveobject.ObjectUUID)

class ProcessTask(Process):
    available = available_tasks()
    TASK_CHOICES = zip(
        ["preingest.tasks."+t for t in available],
        available
    )

    TASK_STATE_CHOICES = zip(celery_states.ALL_STATES,
                             celery_states.ALL_STATES)

    celery_id = models.UUIDField(_('celery id'), max_length=255, null=True, editable=False)
    name = models.CharField(max_length=255, choices=TASK_CHOICES)
    status = models.CharField(_('state'), max_length=50,
                              default=celery_states.PENDING,
                              choices=TASK_STATE_CHOICES)
    params = PickledObjectField(null=True)
    time_started = models.DateTimeField(_('started at'), null=True)
    time_done = models.DateTimeField(_('done at'), null=True)
    traceback = models.TextField(_('traceback'), blank=True, null=True, editable=False)
    hidden = models.BooleanField(editable=False, default=False, db_index=True)
    meta = PickledObjectField(null=True, default=None, editable=False)
    processstep = models.ForeignKey('ProcessStep', related_name='tasks', on_delete=models.CASCADE)
    processstep_pos = models.IntegerField(_('ProcessStep position'), default=0)
    attempt = models.UUIDField(default=uuid.uuid4)
    progress = models.IntegerField(default=0)
    undone = models.BooleanField(default=False)
    undo_type = models.BooleanField(editable=False, default=False)
    retried = models.BooleanField(default=False)

    class Meta:
        db_table = 'ProcessTask'
        ordering = ('processstep_pos',)

        def __unicode__(self):
            return '%s - %s' % (self.name, self.id)

class Nationality(models.Model):
    name = models.CharField(primary_key=True, max_length=128)
    shortname = models.CharField(max_length=2)

    class Meta:
        db_table = 'Nationality'

    def __unicode__(self):
        return '%s (%s)' % (self.name, self.shortname)

class SubmissionAgreement(models.Model):
    name = models.CharField(primary_key=True, max_length=128)

    class Meta:
        db_table = 'SubmissionAgreement'

    def __unicode__(self):
        return '%s' % (self.name)

class Profile(models.Model):
    UNSPECIFIED = "Unspecified"
    COMPLETE = "Complete"

    ProfileState_CHOICES = (
        (0, UNSPECIFIED),
        (10, COMPLETE)
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    state = models.CharField(
            max_length=255,
            choices=ProfileState_CHOICES,
            default=UNSPECIFIED
    )

    submissionAgreement = models.ForeignKey(SubmissionAgreement)
    nationality = models.ForeignKey(Nationality)

    archivistOrganisation = models.CharField(max_length=255)
    archivistOrganisationIdentity = models.CharField(max_length=255)
    archivistOrganisationSoftware = models.CharField(max_length=255)
    archivistOrganisationSoftwareIdentity = models.CharField(max_length=255)
    creatorOrganisation = models.CharField(max_length=255)
    creatorOrganisationIdentity = models.CharField(max_length=255)
    creatorOrganisationSoftware = models.CharField(max_length=255)
    creatorOrganisationSoftwareIdentity = models.CharField(max_length=255)
    producerOrganisation = models.CharField(max_length=255)
    producerIndividual = models.CharField(max_length=255)
    producerOrganisationSoftware = models.CharField(max_length=255)
    producerOrganisationSoftwareIdentity = models.CharField(max_length=255)
    ipOwnerOrganisation = models.CharField(max_length=255)
    ipOwnerIndividual = models.CharField(max_length=255)
    ipOwnerOrganisationSoftware = models.CharField(max_length=255)
    ipOwnerOrganisationSoftwareIdentity = models.CharField(max_length=255)
    editorOrganisation = models.CharField(max_length=255)
    editorIndividual = models.CharField(max_length=255)
    editorOrganisationSoftware = models.CharField(max_length=255)
    editorOrganisationSoftwareIdentity = models.CharField(max_length=255)
    preservationOrganisation = models.CharField(max_length=255)
    preservationIndividual = models.CharField(max_length=255)
    preservationOrganisationSoftware = models.CharField(max_length=255)
    preservationOrganisationSoftwareIdentity = models.CharField(max_length=255)


    class Meta:
        db_table = 'Profile'

    def __unicode__(self):
        return '%s - %s' % (self.name, self.id)

class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.ForeignKey('EventType')
    dateTime = models.DateTimeField(auto_now_add=True, null=True)
    detail = models.CharField(max_length=255)
    application = models.CharField(max_length=50)
    version = models.CharField(max_length=45)
    outcome = models.IntegerField(null=True)
    outcomeDetailNote = models.CharField(max_length=1024)
    linkingAgentIdentifierValue = models.CharField(max_length=45)
    archiveObject = models.ForeignKey('ArchiveObject', related_name='events')

    class Meta:
        db_table = 'Event'

    def __unicode__(self):
        return '%s - %s' % (self.detail, self.id)

class EventType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.IntegerField(null=True)
    desc_sv = models.CharField(max_length=100)
    desc_en = models.CharField(max_length=100)
    localDB = models.IntegerField(null=True)
    externalDB = models.IntegerField(null=True)

    class Meta:
        db_table = 'EventType'

    def __unicode__(self):
        return '%s - %s' % (self.code, self.id)