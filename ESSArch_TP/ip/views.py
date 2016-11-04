import os, shutil

from rest_framework import status
from rest_framework.decorators import detail_route
from rest_framework.response import Response

from ESSArch_Core.configuration.models import (
    EventType,
)

from ESSArch_Core.ip.models import (
    ArchivalInstitution,
    ArchivistOrganization,
    ArchivalType,
    ArchivalLocation,
    InformationPackage,
    EventIP
)

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
    queryset = InformationPackage.objects.all()
    serializer_class = InformationPackageSerializer

    def get_queryset(self):
        queryset = InformationPackage.objects.all()
        archival_institution = self.request.query_params.get('archival_institution')
        archivist_organization = self.request.query_params.get('archivist_organization')
        archival_type = self.request.query_params.get('archival_type')
        archival_location = self.request.query_params.get('archival_location')

        if archival_institution is not None:
            try:
                arch = ArchivalInstitution.objects.get(pk=archival_institution)
                queryset = queryset.filter(ArchivalInstitution=arch)
            except:
                queryset = InformationPackage.objects.none()

        if archivist_organization is not None:
            try:
                arch = ArchivistOrganization.objects.get(pk=archivist_organization)
                queryset = queryset.filter(ArchivistOrganization=arch)
            except:
                queryset = InformationPackage.objects.none()

        if archival_type is not None:
            try:
                arch = ArchivalType.objects.get(pk=archival_type)
                queryset = queryset.filter(ArchivalType=arch)
            except ArchivalType.DoesNotExist:
                queryset = InformationPackage.objects.none()

        if archival_location is not None:
            try:
                arch = ArchivalLocation.objects.get(pk=archival_location)
                queryset = queryset.filter(ArchivalLocation=arch)
            except ArchivalLocation.DoesNotExist:
                queryset = InformationPackage.objects.none()

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return InformationPackageSerializer

        return InformationPackageDetailSerializer

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
        events = ip.events.all()
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
        try:
            InformationPackage.objects.get(pk=pk).create()
            return Response({'status': 'creating ip'})
        except InformationPackage.DoesNotExist:
            return Response(
                {'status': 'Information package with id %s does not exist' % pk},
                status=status.HTTP_404_NOT_FOUND
            )

    @detail_route(methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        """
        Submits the specified information package

        Args:
            pk: The primary key (id) of the information package to submit

        Returns:
            None
        """

        self.get_object().submit()
        return Response({'status': 'submitting ip'})


class EventIPViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows events to be viewed or edited.
    """
    queryset = EventIP.objects.all()
    serializer_class = EventIPSerializer

    def create(self, request):
        """
        """

        detail = request.data.get('eventDetail', None)
        type_id = request.data.get('eventType', None)
        ip_id = request.data.get('information_package', None)

        eventType = EventType.objects.get(pk=type_id)
        ip = InformationPackage.objects.get(pk=ip_id)

        EventIP.objects.create(
            eventDetail=detail, eventType=eventType,
            linkingObjectIdentifierValue=ip
        )
        return Response({"status": "Created event"})
