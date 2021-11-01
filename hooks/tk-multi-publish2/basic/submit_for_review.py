# Copyright (c) 2017 ShotGrid Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the ShotGrid Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the ShotGrid Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by ShotGrid Software Inc.

import hou
import os
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class HoudiniDeadlineSubmitForReviewPlugin(HookBaseClass):
    """
    Plugin for submitting a review from Nuke into ShotGrid.

    """

    @property
    def icon(self):
        """
        Path to an png icon on disk
        """

        # look for icon one level up from this hook's folder in "icons" folder
        return os.path.join(self.disk_location, os.pardir, "icons", "review.png")

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Submit for Review on Deadline"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        review_url = "https://support.ShotGridsoftware.com/hc/en-us/articles/114094032014-The-review-workflow"

        return """<p>
        Submits a movie file to ShotGrid for review. An entry will be
        created in ShotGrid which will include a reference to the movie file's current
        path on disk. Other users will be able to access the file via
        the <b><a href='%s'>review app</a></b> on the ShotGrid website.</p>
        """ % (
            review_url
        )

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to recieve
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts
        as part of its environment configuration.
        """
        return {}

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["*.sequence"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A submit for review task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled.
            This plugin makes use of the tk-multi-reviewsubmission app; if this
            app is not available then the item will not be accepted, this method
            will return a dictionary with the accepted field that has a value of
            False.

            Several properties on the item must also be present for it to be
            accepted. The properties are 'path', 'publish_name', 'color_space',
            'first_frame' and 'last_frame'
        """

        accepted = True
        review_submission_app = self.parent.engine.apps.get(
            "tk-multi-deadlinereviewsubmission"
        )
        if review_submission_app is None:
            accepted = False
            self.logger.debug(
                "Review submission app is not available. skipping item: %s"
                % (item.properties["publish_name"],)
            )
        if item.properties.get("first_frame") is None:
            accepted = False
            self.logger.debug(
                "'first_frame' property is not defined on the item. "
                "Item will be skipped: %s." % (item.properties["publish_name"],)
            )
        if item.properties.get("last_frame") is None:
            accepted = False
            self.logger.debug(
                "'last_frame' property is not defined on the item. "
                "Item will be skipped: %s." % (item.properties["publish_name"],)
            )
        path = item.properties.get("path").replace(os.sep, '/')

        if path is None:
            accepted = False
            self.logger.debug(
                "'path' property is not defined on the item. "
                "Item will be skipped: %s." % (item.properties["publish_name"],)
            )

        if accepted:
            # log the accepted file and display a button to reveal it in the fs
            self.logger.info(
                "Submit for review plugin accepted: %s" % (path,),
                extra={"action_show_folder": {"path": path}},
            )

        # Determine if item should be checked or not
        output_template = item.properties.get("publish_template")
        output_fields = output_template.get_fields(path)

        render_name = output_fields.get('name')

        checked_filenames = ('main', 'beauty', 'master')

        if render_name in checked_filenames:
            checked = True
        else:
            checked = False

        return {"accepted": accepted, "checked": checked}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid and not in proxy mode, False otherwise.
        """

        return True

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        render_path = item.properties.get("path").replace(os.sep, '/')

        sg_publish_data = item.properties.get("sg_publish_data")
        if sg_publish_data is None:
            raise Exception(
                "'sg_publish_data' was not found in the item's properties. "
                "Review Submission for '%s' failed. This property must "
                "be set by a publish plugin that has run before this one." % render_path
            )

        comment = item.description
        tk_multi_deadlinereviewsubmission = self.parent.engine.apps.get(
            "tk-multi-deadlinereviewsubmission"
        )

        publish_template = item.properties.get("publish_template")
        if publish_template is None:
            raise Exception(
                "'work_template' property is missing from item's properties. "
                "Review submission for '%s' failed." % render_path
            )
        if not publish_template.validate(render_path):
            raise Exception(
                "'%s' did not match the render template. "
                "Review submission failed." % render_path
            )

        self.logger.info("Got render path %s" % str(render_path))
        render_path_fields = publish_template.get_fields(render_path)

        first_frame = item.properties.get("first_frame")
        last_frame = item.properties.get("last_frame")
        fps = int(hou.fps())

        filename = hou.hipFile.basename()
        filename = os.path.splitext(filename)[0]

        version = tk_multi_deadlinereviewsubmission.submit_version(
            publish_template,
            render_path_fields,
            [sg_publish_data],
            first_frame,
            last_frame,
            fps,
            filename,
            comment,
        )

        if version:
            self.logger.info(
                "Version uploaded for file: %s" % (render_path,),
                extra={
                    "action_show_in_ShotGrid": {
                        "label": "Show Version",
                        "tooltip": "Reveal the version in ShotGrid.",
                        "entity": version,
                    }
                },
            )
        else:
            raise Exception(
                "Review submission failed. Could not render and "
                "submit the review associated sequence."
            )

    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """
        pass
