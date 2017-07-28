angular.module('myApp').factory('SA', function ($resource, appConfig) {
    return $resource(appConfig.djangoUrl + 'submission-agreements/:id/:action/', {id: "@id"}, {
        get: {
            method: "GET",
            params: { id: "@id" }
        },
    });
});