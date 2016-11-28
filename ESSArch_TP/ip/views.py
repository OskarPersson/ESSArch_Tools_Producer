from _version import get_versions

from collections import OrderedDict

import os, shutil

from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters, status
from rest_framework.decorators import detail_route
from rest_framework.response import Response

from ESSArch_Core.configuration.models import (
    EventType,
    Path,
)

from ESSArch_Core.essxml.Generator.xmlGenerator import (
    downloadSchemas, find_destination
)

from ESSArch_Core.ip.models import (
    ArchivalInstitution,
    ArchivistOrganization,
    ArchivalType,
    ArchivalLocation,
    InformationPackage,
    EventIP
)

from ESSArch_Core.profiles.models import (
    Profile,
    ProfileIP,
)

from ESSArch_Core.util import (
    create_event,
    creation_date,
    timestamp_to_datetime,
)

from ESSArch_Core.WorkflowEngine.models import (
    ProcessStep, ProcessTask,
)

from ip.filters import InformationPackageFilter

from ip.serializers import (
    ArchivalInstitutionSerializer,
    ArchivistOrganizationSerializer,
    ArchivalTypeSerializer,
    ArchivalLocationSerializer,
    InformationPackageSerializer,
    InformationPackageDetailSerializer,
    EventIPSerializer,
)

from preingest.serializers import (
    ProcessStepSerializer,
)

from ip.steps import (
    prepare_ip,
)

from rest_framework import viewsets

class ArchivalInstitutionViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows archival institutions to be viewed or edited.
    """
    queryset = ArchivalInstitution.objects.all()
    serializer_class = ArchivalInstitutionSerializer

class ArchivistOrganizationViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows archivist organizations to be viewed or edited.
    """
    queryset = ArchivistOrganization.objects.all()
    serializer_class = ArchivistOrganizationSerializer

class ArchivalTypeViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows archival types to be viewed or edited.
    """
    queryset = ArchivalType.objects.all()
    serializer_class = ArchivalTypeSerializer

class ArchivalLocationViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows archival locations to be viewed or edited.
    """
    queryset = ArchivalLocation.objects.all()
    serializer_class = ArchivalLocationSerializer


class InformationPackageViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows information packages to be viewed or edited.
    """
    queryset = InformationPackage.objects.all().prefetch_related(
        Prefetch('profileip_set', to_attr='profiles'), 'steps__child_steps',
    )
    serializer_class = InformationPackageSerializer
    filter_backends = (
        filters.OrderingFilter, DjangoFilterBackend, filters.SearchFilter,
    )
    ordering_fields = ('Label', 'Responsible', 'CreateDate', 'State', 'eventDateTime', 'eventDetail', 'id')
    search_fields = ('Label', 'Responsible', 'State', 'SubmissionAgreement__sa_name')
    filter_class = InformationPackageFilter

    def get_serializer_class(self):
        if self.action == 'list':
            return InformationPackageSerializer

        return InformationPackageDetailSerializer

    def get_queryset(self):
        queryset = self.queryset

        other = self.request.query_params.get('other')

        if other is not None:
            queryset = queryset.filter(
                ArchivalInstitution=None,
                ArchivistOrganization=None,
                ArchivalType=None,
                ArchivalLocation=None
            )

        return queryset

    def create(self, request):
        """
        Prepares a new information package (IP) using the following tasks:

        1. Creates a new IP in the database.

        2. Creates a directory in the prepare directory with the name set to
        the id of the new IP.

        3. Creates an event in the database connected to the IP and with the
        detail "Prepare IP".

        Args:

        Returns:
            None
        """


        label = request.data.get('label', None)
        responsible = self.request.user.username or "Anonymous user"

        prepare_ip(label, responsible).run()
        return Response({"status": "Prepared IP"})

    def destroy(self, request, pk=None):
        ip = InformationPackage.objects.get(pk=pk)

        try:
            shutil.rmtree(ip.ObjectPath)
        except:
            pass

        try:
            os.remove(ip.ObjectPath + ".tar")
        except:
            pass

        try:
            os.remove(ip.ObjectPath + ".zip")
        except:
            pass

        return super(InformationPackageViewSet, self).destroy(request, pk=pk)

    @detail_route()
    def events(self, request, pk=None):
        ip = self.get_object()
        events = filters.OrderingFilter().filter_queryset(request, ip.events.all(), self)
        page = self.paginate_queryset(events)
        if page is not None:
            serializers = EventIPSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializers.data)
        serializers = EventIPSerializer(events, many=True, context={'request': request})
        return Response(serializers.data)

    @detail_route()
    def steps(self, request, pk=None):
        ip = self.get_object()
        steps = ip.steps.all()
        serializer = ProcessStepSerializer(
            data=steps, many=True, context={'request': request}
        )
        serializer.is_valid()
        return Response(serializer.data)

    @detail_route(methods=['post'], url_path='create')
    def create_ip(self, request, pk=None):
        """
        Creates the specified information package

        Args:
            pk: The primary key (id) of the information package to create

        Returns:
            None
        """

        ip = self.get_object()

        validators = request.data.get('validators', {})

        validate_xml_file = validators.get('validate_xml_file', False)
        validate_file_format = validators.get('validate_file_format', False)
        validate_integrity = validators.get('validate_integrity', False)
        validate_logical_physical_representation = validators.get('validate_logical_physical_representation', False)

        container_format = ip.get_container_format()

        t0 = ProcessTask.objects.create(
            name="preingest.tasks.UpdateIPStatus",
            params={
                "ip": ip,
                "status": "Creating",
            },
            processstep_pos=0,
            information_package=ip
        )
        start_create_sip_step = ProcessStep.objects.create(
            name="Update IP Status",
            parent_step_pos=0
        )

        start_create_sip_step.tasks.add(t0)

        event_type = EventType.objects.get(eventType=10200)

        create_event(event_type, 0, "Created SIP", get_versions()['version'], "System", ip=ip)

        prepare_path = Path.objects.get(
            entity="path_preingest_prepare"
        ).value

        reception_path = Path.objects.get(
            entity="path_preingest_reception"
        ).value

        ip_prepare_path = os.path.join(prepare_path, str(ip.pk))
        ip_reception_path = os.path.join(reception_path, str(ip.pk))
        events_path = os.path.join(ip_prepare_path, "ipevents.xml")

        structure = ip.get_profile('sip').structure

        info = ip.get_profile('sip').specification_data
        info["_OBJID"] = str(ip.pk)
        info["_OBJLABEL"] = ip.Label

        # ensure premis is created before mets
        filesToCreate = OrderedDict()

        if ip.profile_locked('preservation_metadata'):
            premis_profile = ip.get_profile('preservation_metadata')
            premis_dir, premis_name = find_destination("preservation_description_file", structure)
            premis_path = os.path.join(ip.ObjectPath, premis_dir, premis_name)
            filesToCreate[premis_path] = premis_profile.specification

        mets_dir, mets_name = find_destination("mets_file", structure)
        mets_path = os.path.join(ip.ObjectPath, mets_dir, mets_name)
        filesToCreate[mets_path] = ip.get_profile('sip').specification

        for fname, template in filesToCreate.iteritems():
            dirname = os.path.dirname(fname)
            downloadSchemas(
                template, dirname, structure=structure, root=ip.ObjectPath
            )

        t1 = ProcessTask.objects.create(
            name="preingest.tasks.GenerateXML",
            params={
                "info": info,
                "filesToCreate": filesToCreate,
                "folderToParse": ip_prepare_path,
                "algorithm": ip.get_checksum_algorithm(),
            },
            processstep_pos=3,
            information_package=ip
        )

        generate_xml_step = ProcessStep.objects.create(
            name="Generate XML",
            parent_step_pos=1
        )
        generate_xml_step.tasks = [t1]
        generate_xml_step.save()

        #dirname = os.path.join(ip_prepare_path, "data")

        validate_step = ProcessStep.objects.create(
            name="Validation",
            parent_step_pos=2
        )

        if validate_xml_file:
            validate_step.tasks.add(
                ProcessTask.objects.create(
                    name="preingest.tasks.ValidateXMLFile",
                    params={
                        "xml_filename": mets_path,
                    },
                    processstep_pos=1,
                    information_package=ip
                )
            )

            if ip.profile_locked("preservation_metadata"):
                validate_step.tasks.add(
                    ProcessTask.objects.create(
                        name="preingest.tasks.ValidateXMLFile",
                        params={
                            "xml_filename": premis_path,
                        },
                        processstep_pos=2,
                        information_package=ip
                    )
                )

        if validate_logical_physical_representation:
            validate_step.tasks.add(
                ProcessTask.objects.create(
                    name="preingest.tasks.ValidateLogicalPhysicalRepresentation",
                    params={
                        "dirname": ip.ObjectPath,
                        "xmlfile": mets_path,
                    },
                    processstep_pos=3,
                    information_package=ip
                )
            )

        validate_step.tasks.add(
            ProcessTask.objects.create(
                name="ESSArch_Core.tasks.ValidateFiles",
                params={
                    "ip": ip,
                    "xmlfile": mets_path,
                    "validate_fileformat": validate_file_format,
                    "validate_integrity": validate_integrity,
                },
                processstep_pos=4,
                information_package=ip
            )
        )

        validate_step.save()

        info = ip.get_profile('event').specification_data
        info["_OBJID"] = str(ip.pk)
        info["_OBJLABEL"] = ip.Label

        filesToCreate = OrderedDict()
        filesToCreate[events_path] = ip.get_profile('event').specification

        for fname, template in filesToCreate.iteritems():
            dirname = os.path.dirname(fname)
            downloadSchemas(
                template, dirname, structure=structure, root=ip.ObjectPath
            )

        create_sip_step = ProcessStep.objects.create(
                name="Create SIP",
                parent_step_pos=3
        )

        create_sip_step.tasks.add(ProcessTask.objects.create(
            name="preingest.tasks.GenerateXML",
            params={
                "info": info,
                "filesToCreate": filesToCreate,
                "algorithm": ip.get_checksum_algorithm(),
            },
            processstep_pos=0,
            information_package=ip
        ))

        create_sip_step.tasks.add(ProcessTask.objects.create(
            name="preingest.tasks.AppendEvents",
            params={
                "filename": events_path,
            },
            processstep_pos=1,
            information_package=ip
        ))

        spec = {
            "-name": "object",
            "-namespace": "premis",
            "-children": [
                {
                    "-name": "objectIdentifier",
                    "-namespace": "premis",
                    "-children": [
                        {
                            "-name": "objectIdentifierType",
                            "-namespace": "premis",
                            "#content": [{"var": "FIDType"}],
                            "-children": []
                        },
                        {
                            "-name": "objectIdentifierValue",
                            "-namespace": "premis",
                            "#content": [{"var": "FID"}],
                            "-children": []
                        }
                    ]
                },
                {
                    "-name": "objectCharacteristics",
                    "-namespace": "premis",
                    "-children": [
                        {
                            "-name": "format",
                            "-namespace": "premis",
                            "-children": [
                                {
                                    "-name": "formatDesignation",
                                    "-namespace": "premis",
                                    "-children": [
                                        {
                                            "-name": "formatName",
                                            "-namespace": "premis",
                                            "#content": [{"var": "FFormatName"}],
                                            "-children": []
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                {
                    "-name": "storage",
                    "-namespace": "premis",
                    "-children": [
                        {
                            "-name": "contentLocation",
                            "-namespace": "premis",
                            "-children": [
                                {
                                    "-name": "contentLocationType",
                                    "-namespace": "premis",
                                    "#content": [{"var": "FLocationType"}],
                                    "-children": []
                                },
                                {
                                    "-name": "contentLocationValue",
                                    "-namespace": "premis",
                                    "#content": [{"text": "file:///%s.%s" % (ip.pk, container_format.lower())}],
                                    "-children": []
                                }
                            ]
                        }
                    ]
                }
            ],
            "-attr": [
                {
                  "-name": "type",
                  '-namespace': 'xsi',
                  "-req": "1",
                  "#content": [{"text":"premis:file"}]
                }
            ],
        }

        info = {
            'FIDType': "UUID",
            'FID': ip.ObjectIdentifierValue,
            'FFormatName': container_format.upper(),
            'FLocationType': 'URI',
            'FName': ip.ObjectPath,
        }

        create_sip_step.tasks.add(ProcessTask.objects.create(
            name="ESSArch_Core.tasks.InsertXML",
            params={
                "filename": events_path,
                "elementToAppendTo": "premis",
                "spec": spec,
                "info": info,
                "index": 0
            },
            processstep_pos=2,
            information_package=ip
        ))

        if validate_xml_file:
            create_sip_step.tasks.add(
                ProcessTask.objects.create(
                    name="preingest.tasks.ValidateXMLFile",
                    params={
                        "xml_filename": events_path,
                    },
                    processstep_pos=3,
                    information_package=ip
                )
            )


        if container_format.lower() == 'zip':
            zipname = os.path.join(ip_reception_path) + '.zip'
            container_task = ProcessTask.objects.create(
                name="preingest.tasks.CreateZIP",
                params={
                    "dirname": ip_prepare_path,
                    "zipname": zipname,
                },
                processstep_pos=4,
                information_package=ip
            )

        else:
            tarname = os.path.join(ip_reception_path) + '.tar'
            container_task = ProcessTask.objects.create(
                name="preingest.tasks.CreateTAR",
                params={
                    "dirname": ip_prepare_path,
                    "tarname": tarname,
                },
                processstep_pos=4,
                information_package=ip
            )

        create_sip_step.tasks.add(container_task)

        create_sip_step.tasks.add(
            ProcessTask.objects.create(
                name="preingest.tasks.UpdateIPPath",
                params={
                    "ip": ip,
                },
                result_params={
                    "path": container_task.pk
                },
                processstep_pos=5,
                information_package=ip
            )
        )

        create_sip_step.tasks.add(
            ProcessTask.objects.create(
                name="preingest.tasks.UpdateIPStatus",
                params={
                    "ip": ip,
                    "status": "Created",
                },
                processstep_pos=6,
                information_package=ip
            )
        )

        create_sip_step.save()

        main_step = ProcessStep.objects.create(
            name="Create SIP",
        )
        main_step.child_steps = [
            start_create_sip_step, generate_xml_step, validate_step,
            create_sip_step
        ]
        main_step.information_package = ip
        main_step.save()
        main_step.run()

        return Response({'status': 'creating ip'})

    @detail_route(methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        """
        Submits the specified information package

        Args:
            pk: The primary key (id) of the information package to submit

        Returns:
            None
        """

        ip = self.get_object()

        step = ProcessStep.objects.create(
            name="Submit SIP",
            information_package = ip
        )

        step.tasks.add(ProcessTask.objects.create(
            name="preingest.tasks.UpdateIPStatus",
            params={
                "ip": ip,
                "status": "Submitting",
            },
            processstep_pos=0,
            information_package=ip
        ))

        reception = Path.objects.get(entity="path_preingest_reception").value

        sd_profile = ip.get_profile('submit_description')

        container_format = ip.get_container_format()
        container_file = os.path.join(reception, str(ip.pk) + ".%s" % container_format.lower())

        sa = ip.SubmissionAgreement

        info = sd_profile.specification_data
        info["_OBJID"] = str(ip.pk)
        info["_OBJLABEL"] = str(ip.Label)
        info["_IP_CREATEDATE"] = timestamp_to_datetime(creation_date(container_file)).isoformat()
        info["_SA_ID"] = str(sa.pk)

        try:
            info["_PROFILE_TRANSFER_PROJECT_ID"] = str(ip.get_profile('transfer_project').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_SUBMIT_DESCRIPTION_ID"] = str(ip.get_profile('submit_description').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_SIP_ID"] = str(ip.get_profile('sip').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_AIP_ID"] = str(ip.get_profile('aip').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_DIP_ID"] = str(ip.get_profile('dip').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_CONTENT_TYPE_ID"] = str(ip.get_profile('content_type').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_AUTHORITY_INFORMATION_ID"] = str(ip.get_profile('authority_information').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_ARCHIVAL_DESCRIPTION_ID"] = str(ip.get_profile('archival_description').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_PRESERVATION_METADATA_ID"] = str(ip.get_profile('preservation_metadata').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_EVENT_ID"] = str(ip.get_profile('event').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_DATA_SELECTION_ID"] = str(ip.get_profile('data_selection').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_IMPORT_ID"] = str(ip.get_profile('import').pk)
        except AttributeError:
            pass

        try:
            info["_PROFILE_WORKFLOW_ID"] = str(ip.get_profile('workflow').pk)
        except AttributeError:
            pass


        infoxml = os.path.join(reception, str(ip.pk) + ".xml")

        filesToCreate = {
            infoxml: sd_profile.specification
        }

        step.tasks.add(ProcessTask.objects.create(
            name="preingest.tasks.GenerateXML",
            params={
                "info": info,
                "filesToCreate": filesToCreate,
                "folderToParse": container_file,
                "algorithm": ip.get_checksum_algorithm(),
            },
            processstep_pos=1,
            information_package=ip
        ))

        step.tasks.add(ProcessTask.objects.create(
            name="preingest.tasks.SubmitSIP",
            params={
                "ip": ip
            },
            processstep_pos=2,
            information_package=ip
        ))

        step.tasks.add(ProcessTask.objects.create(
            name="preingest.tasks.UpdateIPStatus",
            params={
                "ip": ip,
                "status": "Submitted"
            },
            processstep_pos=3,
            information_package=ip
        ))

        step.save()
        step.run()

        return Response({'status': 'submitting ip'})

    @detail_route(methods=['put'], url_path='check-profile')
    def check_profile(self, request, pk=None):
        ip = self.get_object()
        ptype = request.data.get("type")

        try:
            pip = ProfileIP.objects.get(ip=ip, profile__profile_type=ptype)

            if not pip.LockedBy:
                pip.included = request.data.get('checked', not pip.included)
                pip.save()
        except ProfileIP.DoesNotExist:
            print "pip does not exist"
            pass

        return Response()

    @detail_route(methods=['put'], url_path='change-profile')
    def change_profile(self, request, pk=None):
        ip = self.get_object()
        new_profile = Profile.objects.get(pk=request.data["new_profile"])

        ip.change_profile(new_profile)

        return Response({
            'status': 'updating IP (%s) with new profile (%s)' % (
                ip.pk, new_profile
            )
        })

    @detail_route(methods=['post'], url_path='unlock-profile')
    def unlock_profile(self, request, pk=None):
        ip = self.get_object()
        ptype = request.data.get("type")

        if ptype:
            ip.unlock_profile(ptype)
            return Response({
                'status': 'unlocking profile with type "%s" in IP "%s"' % (
                    ptype, ip.pk
                )
            })

        return Response()

class EventIPViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows events to be viewed or edited.
    """
    queryset = EventIP.objects.all()
    serializer_class = EventIPSerializer
    filter_backends = (
        filters.OrderingFilter, DjangoFilterBackend,
    )
    ordering_fields = ('id', 'eventDetail', 'eventDateTime')

    def create(self, request):
        """
        """

        outcomeDetailNote = request.data.get('eventOutcomeDetailNote', None)
        outcome = request.data.get('eventOutcome', 0)
        type_id = request.data.get('eventType', None)
        ip_id = request.data.get('information_package', None)

        eventType = EventType.objects.get(pk=type_id)
        ip = InformationPackage.objects.get(pk=ip_id)

        EventIP.objects.create(
            eventOutcome=outcome, eventOutcomeDetailNote=outcomeDetailNote,
            eventType=eventType, linkingObjectIdentifierValue=ip,
            linkingAgentIdentifierValue="System"
        )
        return Response({"status": "Created event"})
