/*
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
*/

angular.module('essarch.controllers').controller('BaseCtrl', function (vm, IP, Profile, Step, Task, ipSortString, $log, $uibModal, $timeout, $scope, $window, $location, $sce, $http, myService, appConfig, $state, $stateParams, $rootScope, listViewService, $interval, Resource, $translate, $cookies, $filter, $anchorScroll, PermPermissionStore, $q, ContextMenuBase){
    vm.itemsPerPage = $cookies.get('etp-ips-per-page') || 10;
    $scope.updateIpsPerPage = function(items) {
        $cookies.put('etp-ips-per-page', items);
    };

    // Initialize variables
    $scope.max = 100;
    $scope.stepTaskInfoShow = false;
    $scope.statusShow = false;
    $scope.eventShow = false;
    $scope.select = false;
    $scope.subSelect = false;
    $scope.edit = false;
    $scope.eventlog = false;
    $scope.filebrowser = false;
    $scope.ip = null;
    $rootScope.ip = null;

    // Tree control for state tree

    var watchers = [];
    // Watchers
    watchers.push($scope.$watch(function(){return $rootScope.navigationFilter;}, function(newValue, oldValue) {
        $scope.getListViewData();
    }, true));

    // Init intervals
    // If status view is visible, start update interval
    $scope.$on('$stateChangeStart', function () {
        $interval.cancel(listViewInterval);
        watchers.forEach(function(watcher) {
            watcher();
        });
    });

    $scope.$on('REFRESH_LIST_VIEW', function (event, data) {
        $scope.getListViewData();
    });

    $scope.$on('RELOAD_IP', function (event, data) {
        $http.get(appConfig.djangoUrl + "information-packages/" + $scope.ip.id + "/").then(function(response) {
            $scope.ip = response.data;
            $rootScope.ip = response.data;
        });
    });

    // Context menu

    $scope.menuOptions = function (rowType, row) {
        return [
            ContextMenuBase.changeOrganization(
                function () {
                    $scope.ip = row;
                    $rootScope.ip = row;
                    vm.changeOrganizationModal($scope.ip);
            })
        ];
    }

    //Update ip list view with an interval
    //Update only if status < 100 and no step has failed in any IP
    var listViewInterval;
    vm.updateListViewConditional = function() {
        $interval.cancel(listViewInterval);
        listViewInterval = $interval(function() {
            var updateVar = false;
            vm.displayedIps.forEach(function(ip, idx) {
                if(ip.status < 100) {
                    if(ip.step_state != "FAILURE") {
                        updateVar = true;
                    }
                }
            });
            if(updateVar) {
                $scope.getListViewData();
            } else {
                $interval.cancel(listViewInterval);
                listViewInterval = $interval(function() {
                    var updateVar = false;
                    vm.displayedIps.forEach(function(ip, idx) {
                        if(ip.status < 100) {
                            if(ip.step_state != "FAILURE") {
                                updateVar = true;
                            }
                        }
                    });
                    if(!updateVar) {
                        $scope.getListViewData();
                    } else {
                        vm.updateListViewConditional();
                    }

                }, appConfig.ipIdleInterval);
            }
        }, appConfig.ipInterval);
    };
    vm.updateListViewConditional();

    // Click functions
    $scope.stateClicked = function (row) {
        if ($scope.statusShow) {
            $scope.tree_data = [];
            if ($scope.ip == row) {
                $scope.statusShow = false;
                if(!$scope.select && !$scope.edit && !$scope.statusShow && !$scope.eventShow && !$scope.filebrowser) {
                    $scope.ip = null;
                    $rootScope.ip = null;
                }
            } else {
                $scope.statusShow = true;
                $scope.edit = false;
                $scope.ip = row;
                $rootScope.ip = row;
            }
        } else {
            $scope.statusShow = true;
            $scope.edit = false;
            $scope.ip = row;
            $rootScope.ip = row;
        }
        $scope.subSelect = false;
        $scope.eventlog = false;
        $scope.select = false;
        $scope.eventShow = false;
    };

    $scope.eventsClick = function (row) {
        if($scope.eventShow && $scope.ip == row){
            $scope.eventShow = false;
            $rootScope.stCtrl = null;
            if(!$scope.select && !$scope.edit && !$scope.statusShow && !$scope.eventShow && !$scope.filebrowser) {
                $scope.ip = null;
                $rootScope.ip = null;
            }
        } else {
            $scope.eventShow = true;
            $scope.statusShow = false;
            $scope.ip = row;
            $rootScope.ip = row;
        }
        $scope.select = false;
        $scope.edit = false;
        $scope.eventlog = false;
    };

    $scope.filebrowserClick = function (ip) {
        if ($scope.filebrowser && $scope.ip == ip) {
            $scope.filebrowser = false;
            if(!$scope.select && !$scope.edit && !$scope.statusShow && !$scope.eventShow && !$scope.filebrowser) {
                $scope.ip = null;
                $rootScope.ip = null;
            }
        } else {
            if ($rootScope.auth.id == ip.responsible.id || !ip.responsible) {
                $scope.filebrowser = true;
                $scope.ip = ip;
                $rootScope.ip = ip;
            }
        }
    }

    // List view

    vm.displayedIps = [];
    //Get data according to ip table settings and populates ip table
    vm.callServer = function callServer(tableState) {
        $scope.ipLoading = true;
        if (vm.displayedIps.length == 0) {
            $scope.initLoad = true;
        }
        if (!angular.isUndefined(tableState)) {
            $scope.tableState = tableState;
            var search = "";
            if (tableState.search.predicateObject) {
                var search = tableState.search.predicateObject["$"];
            }
            var sorting = tableState.sort;
            var pagination = tableState.pagination;
            var start = pagination.start || 0;     // This is NOT the page number, but the index of item in the list that you want to use to display the table.
            var number = pagination.number || vm.itemsPerPage;  // Number of entries showed per page.
            var pageNumber = start / number + 1;

            Resource.getIpPage(start, number, pageNumber, tableState, sorting, search, ipSortString, $scope.columnFilters).then(function (result) {
                vm.displayedIps = result.data;
                tableState.pagination.numberOfPages = result.numberOfPages;//set the number of pages so the pagination can update
                $scope.ipLoading = false;
                $scope.initLoad = false;
                ipExists();
            }).catch(function(response) {
                if(response.status == 404) {
                    var filters = angular.extend({
                        state: ipSortString
                    }, $scope.columnFilters)

                    if(vm.workarea) {
                        filters.workarea = vm.workarea;
                    }

                    listViewService.checkPages("ip", number, filters).then(function (result) {
                        tableState.pagination.numberOfPages = result.numberOfPages;//set the number of pages so the pagination can update
                        tableState.pagination.start = (result.numberOfPages*number) - number;
                        vm.callServer(tableState);
                    });
                }
            });
        }
    };

    function ipExists() {
        if($scope.ip != null) {
            var temp = false;
            vm.displayedIps.forEach(function(aic) {
                if($scope.ip.id == aic.id) {
                    temp = true;
                }
            })
            if(!temp) {
                $scope.eventShow = false;
                $scope.statusShow = false;
                $scope.filebrowser = false;
                $scope.requestForm = false;
                $scope.eventlog = false;
                $scope.requestEventlog = false;
            }
        }
    }

    //Get data for list view
    $scope.getListViewData = function() {
        vm.callServer($scope.tableState);
        $rootScope.loadNavigation(ipSortString);
    };

    function selectNextIp() {
        var index = 0;
        if($scope.ip) {
            vm.displayedIps.forEach(function(ip, idx, array) {
                if($scope.ip.id === ip.id) {
                    index = idx+1;
                }
            });
        }
        if(index !== vm.displayedIps.length) {
            $scope.ipTableClick(vm.displayedIps[index]);
        }
    }

    function previousIp() {
        var index = vm.displayedIps.length-1;
        if($scope.ip) {
            vm.displayedIps.forEach(function(ip, idx, array) {
                if($scope.ip.id === ip.id) {
                    index = idx-1;
                }
            });
        }
        if(index >= 0) {
            $scope.ipTableClick(vm.displayedIps[index]);
        }
    }

    function closeContentViews() {
        $scope.stepTaskInfoShow = false;
        $scope.statusShow = false;
        $scope.eventShow = false;
        $scope.select = false;
        $scope.subSelect = false;
        $scope.edit = false;
        $scope.eventlog = false;
        $scope.filebrowser = false;
        $scope.ip = null;
        $rootScope.ip = null;
    }
    var arrowLeft = 37;
    var arrowUp = 38;
    var arrowRight = 39;
    var arrowDown = 40;
    var escape = 27;
    var enter = 13;
    var space = 32;

    /**
     * Handle keydown events in list view
     * @param {Event} e
     */
    vm.ipListKeydownListener = function(e) {
        switch(e.keyCode) {
            case arrowDown:
                e.preventDefault();
                selectNextIp();
                break;
            case arrowUp:
                e.preventDefault();
                previousIp();
                break;
            case arrowLeft:
                e.preventDefault();
                var pagination = $scope.tableState.pagination;
                if(pagination.start != 0) {
                    pagination.start -= pagination.number;
                    $scope.getListViewData();
                }
                break;
            case arrowRight:
                e.preventDefault();
                var pagination = $scope.tableState.pagination;
                if((pagination.start / pagination.number + 1) < pagination.numberOfPages) {
                    pagination.start+=pagination.number;
                    $scope.getListViewData();
                }
                break;
            case escape:
                if($scope.ip) {
                    closeContentViews();
                }
                break;
        }
    }

    /**
     * Handle keydown events in views outside list view
     * @param {Event} e
     */
    vm.contentViewsKeydownListener = function(e) {
        switch(e.keyCode) {
            case escape:
                if($scope.ip) {
                    closeContentViews();
                }
                document.getElementById("list-view").focus();
                break;
        }
    }

    // Functions associated with profiles

    //populating select view
    $scope.selectRowCollection = [];
    $scope.selectRowCollapse = [];

    //Gets all submission agreement profiles
    $scope.getSaProfiles = function (ip) {
        $scope.selectRowCollapse = [];
        listViewService.getSaProfiles(ip).then(function (value) {
            $scope.saProfile = value;
            var promises = [];
            for(var key in  $scope.saProfile.profile) {
                if (/^profile/.test(key) && $scope.saProfile.profile[key] != null) {
                    promises.push(Profile.get({ id: $scope.saProfile.profile[key] }).$promise.then(function(resource) {
                        $scope.selectRowCollapse.push(resource);
                        return resource;
                    }));
                }
            }
            $q.all(promises).then(function() {
                $scope.selectRowCollection = $scope.selectRowCollapse;
                return $scope.saProfile;
            })
            //$scope.getSelectCollection(value.profile, ip)
        });
    };

    //Get All profiles and populates the select view table array
    $scope.getSelectCollection = function (sa, ip) {
        $scope.selectRowCollapse = listViewService.getProfilesFromIp(sa, ip)
    };

    // Initialize validator fields

    vm.validatorModel = {
    };
    vm.validatorFields = [
        {
            "templateOptions": {
                "type": "text",
                "label": $translate.instant('VALIDATEFILEFORMAT'),
            },
            "defaultValue": true,
            "type": "checkbox",
            "ngModelElAttrs": {
                "tabindex": '-1'
            },
            "key": "validate_file_format",
        },
        {
            "templateOptions": {
                "type": "text",
                "label": $translate.instant('VALIDATEXMLFILE'),
            },
            "defaultValue": true,
            "type": "checkbox",
            "ngModelElAttrs": {
                "tabindex": '-1'
            },
            "key": "validate_xml_file",
        },
        {
            "templateOptions": {
                "type": "text",
                "label": $translate.instant('VALIDATELOGICALPHYSICALREPRESENTATION'),
            },
            "defaultValue": true,
            "type": "checkbox",
            "ngModelElAttrs": {
                "tabindex": '-1'
            },
            "key": "validate_logical_physical_representation",
        },
        {
            "templateOptions": {
                "type": "text",
                "label": $translate.instant('VALIDATEINTEGRITY'),
            },
            "defaultValue": true,
            "type": "checkbox",
            "ngModelElAttrs": {
                "tabindex": '-1'
            },
            "key": "validate_integrity",
        }
    ];

    // file conversion

    vm.fileConversionModel = {};
    $translate(['YES', 'NO']).then(function(translations) {
        vm.fileConversionFields = [
            {
                "templateOptions": {
                    "type": "text",
                    "label": $translate.instant('CONVERTFILES'),
                    "options": [{name: translations.YES, value: true},{name: translations.NO, value: false}],
                },
                "defaultValue": false,
                "type": "select",
                "ngModelElAttrs": {
                    "tabindex": '-1'
                },
                "key": "file_conversion",
            },
        ];

    });

    // Basic functions

    //Get data for eventlog view
    vm.getEventlogData = function() {
        listViewService.getEventlogData().then(function(value){
            $scope.eventTypeCollection = value;
        });
    };

    //Adds a new event to the database
    $scope.addEvent = function(ip, eventType, eventDetail) {
        listViewService.addEvent(ip, eventType, eventDetail).then(function(value) {
        });
    }

    $scope.extendedEqual = function(specification_data, model) {
        for(var prop in model) {
            if((model[prop] != "" || specification_data[prop]) && model[prop] != specification_data[prop]){
                return false;
            }
        }
        return true;
    };

    //advanced filter form data
    $scope.columnFilters = {};
    $scope.filterModel = {};
    $scope.options = {};
    $scope.fields = [];
    vm.setupForm = function() {
        $scope.fields = [];
        $scope.filterModel = {};
        for (var key in $scope.usedColumns) {
            var column = $scope.usedColumns[key];
            switch (column.type) {
                case "ModelChoiceFilter":
                case "ChoiceFilter":
                    $scope.fields.push({
                        "templateOptions": {
                            "type": "text",
                            "label": $translate.instant(key.toUpperCase()),
                            "labelProp": "display_name",
                            "valueProp": "value",
                            "options": column.choices,
                        },
                        "type": "select",
                        "key": key,
                    })
                    break;
                case "BooleanFilter":
                    $scope.fields.push({
                        "templateOptions": {
                            "label": $translate.instant(key.toUpperCase()),
                            "labelProp": key,
                            "valueProp": key,
                        },
                        "type": "checkbox",
                        "key": key,
                    })
                    break;
                case "ListFilter":
                case "CharFilter":
                    $scope.fields.push({
                        "templateOptions": {
                            "type": "text",
                            "label": $translate.instant(key.toUpperCase()),
                            "labelProp": key,
                            "valueProp": key,
                        },
                        "type": "input",
                        "key": key,
                    })
                    break;
                case "IsoDateTimeFromToRangeFilter":
                    $scope.fields.push(
                        {
                            "templateOptions": {
                                "type": "text",
                                "label": $translate.instant(key.toUpperCase() + "_START"),
                            },
                            "type": "datepicker",
                            "key": key + "_0"
                        }
                    )
                    $scope.fields.push(
                        {
                            "templateOptions": {
                                "type": "text",
                                "label": $translate.instant(key.toUpperCase() + "_END"),
                            },
                            "type": "datepicker",
                            "key": key + "_1"
                        }
                    )
                    break;
             }
         }
    }

    vm.toggleOwnIps = function(filterIps) {
        if(filterIps) {
            $scope.filterModel.responsible = $rootScope.auth.username;
        } else {
            if($scope.filterModel.responsible == $rootScope.auth.username) {
                delete $scope.filterModel.responsible;
            }
        }
    }

    //Toggle visibility of advanced filters
    $scope.toggleAdvancedFilters = function () {
        if ($scope.showAdvancedFilters) {
            $scope.showAdvancedFilters = false;
        } else {
            if ($scope.fields.length <=0) {
                $http({
                    method: "OPTIONS",
                    url: appConfig.djangoUrl + "information-packages/"
                }).then(function(response) {
                    $scope.usedColumns = response.data.filters;
                    vm.setupForm();
                });
            }
            $scope.showAdvancedFilters = true;
        }
         if ($scope.showAdvancedFilters) {
             $window.onclick = function (event) {
                 var clickedElement = $(event.target);
                 if (!clickedElement) return;
                 var elementClasses = event.target.classList;
                 var clickedOnAdvancedFilters = elementClasses.contains('filter-icon') ||
                 elementClasses.contains('advanced-filters') ||
                 clickedElement.parents('.advanced-filters').length ||
                 clickedElement.parents('.button-group').length;

                 if (!clickedOnAdvancedFilters) {
                     $scope.showAdvancedFilters = !$scope.showAdvancedFilters;
                     $window.onclick = null;
                     $scope.$apply();
                 }
             }
         } else {
             $window.onclick = null;
         }
    }

    $scope.clearSearch = function() {
        delete $scope.tableState.search.predicateObject;
        $('#search-input')[0].value = "";
        $scope.getListViewData();
    }

    $scope.filterActive = function() {
        var temp = false;
        for(var key in $scope.columnFilters) {
            if($scope.columnFilters[key] !== "" && $scope.columnFilters[key] !== null) {
                temp = true;
            }
        }
        return temp;
    }

    $scope.submitAdvancedFilters = function() {
        $scope.columnFilters = angular.copy($scope.filterModel);
        $scope.getListViewData();
    }

    // Click function for request form submit.
    // Replaced form="vm.requestForm" to work in IE
    $scope.clickSubmit = function () {
        if (vm.requestForm.$valid) {
            $scope.submitRequest($scope.ip, vm.request);
        }
    }

    $scope.tracebackModal = function (profiles) {
        $scope.profileToSave = profiles;
        var modalInstance = $uibModal.open({
            animation: true,
            ariaLabelledBy: 'modal-title',
            ariaDescribedBy: 'modal-body',
            templateUrl: 'static/frontend/views/task_traceback_modal.html',
            scope: $scope,
            size: 'lg',
            controller: 'ModalInstanceCtrl',
            controllerAs: '$ctrl'
        })
        modalInstance.result.then(function (data) {
        }, function () {
            $log.info('modal-component dismissed at: ' + new Date());
        });
    }
    //Creates and shows modal with task information
    $scope.taskInfoModal = function () {
        var modalInstance = $uibModal.open({
            animation: true,
            ariaLabelledBy: 'modal-title',
            ariaDescribedBy: 'modal-body',
            templateUrl: 'modals/task_info_modal.html',
            scope: $scope,
            controller: 'TaskInfoModalInstanceCtrl',
            controllerAs: '$ctrl',
            resolve: {
                data: {}
            }
        });
        modalInstance.result.then(function (data, $ctrl) {
        }, function () {
            $log.info('modal-component dismissed at: ' + new Date());
        });
    }
    //Creates and shows modal with step information
    $scope.stepInfoModal = function () {
        var modalInstance = $uibModal.open({
            animation: true,
            ariaLabelledBy: 'modal-title',
            ariaDescribedBy: 'modal-body',
            templateUrl: 'modals/step_info_modal.html',
            scope: $scope,
            controller: 'StepInfoModalInstanceCtrl',
            controllerAs: '$ctrl',
            resolve: {
                data: {}
            }
        });
        modalInstance.result.then(function (data, $ctrl) {
        }, function () {
            $log.info('modal-component dismissed at: ' + new Date());
        });
    }
    //Create and show modal for remove ip
    $scope.removeIpModal = function (ipObject) {
        var modalInstance = $uibModal.open({
            animation: true,
            ariaLabelledBy: 'modal-title',
            ariaDescribedBy: 'modal-body',
            templateUrl: 'static/frontend/views/remove-ip-modal.html',
            controller: 'DataModalInstanceCtrl',
            controllerAs: '$ctrl',
            resolve: {
                data: {
                    ip: ipObject
                }
            }
        })
        modalInstance.result.then(function (data) {
            vm.displayedIps.splice(vm.displayedIps.indexOf(ipObject), 1);
            $scope.edit = false;
            $scope.select = false;
            $scope.eventlog = false;
            $scope.eventShow = false;
            $scope.statusShow = false;
            $scope.filebrowser = false;
            $rootScope.loadNavigation(ipSortString);
            if(vm.displayedIps.length == 0) {
                $state.reload();
            }
            $scope.getListViewData();
        }, function () {
            $log.info('modal-component dismissed at: ' + new Date());
        });
    }

    vm.changeOrganizationModal = function (ip) {
        var modalInstance = $uibModal.open({
            animation: true,
            ariaLabelledBy: 'modal-title',
            ariaDescribedBy: 'modal-body',
            templateUrl: 'modals/change_organization_modal.html',
            controller: 'OrganizationModalInstanceCtrl',
            controllerAs: '$ctrl',
            size: "sm",
            resolve: {
                data: function () {
                    return {
                        ip: ip,
                    };
                }
            },
        })
        modalInstance.result.then(function (data) {
            $scope.getListViewData();
        }).catch(function () {
            $log.info('modal-component dismissed at: ' + new Date());
        });
    }
});
