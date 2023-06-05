# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import hou
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

# A dict of dicts organized by category, type and output file parm
_HOUDINI_OUTPUTS = {
    # rops
    hou.ropNodeTypeCategory(): {
        "alembic": "filename",  # alembic cache
        "comp": "copoutput",  # composite
        "ifd": "vm_picture",  # mantra render node
        "opengl": "picture",  # opengl render
        "wren": "wr_picture",  # wren wireframe
    },
}


class HoudiniSessionCollector(HookBaseClass):
    """
    Collector that operates on the current houdini session. Should inherit from
    the basic collector hook.
    """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.
        A dictionary on the following form::
            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }
        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """

        # grab any base class settings
        collector_settings = super(HoudiniSessionCollector, self).settings or {}

        # settings specific to this collector
        houdini_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                "correspond to a template defined in "
                "templates.yml. If configured, is made available"
                "to publish plugins via the collected item's "
                "properties. ",
            },
        }

        # update the base settings with these settings
        collector_settings.update(houdini_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current Houdini session and parents a subtree of items
        under the parent_item passed in.
        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """
        # create an item representing the current houdini session
        item = self.collect_current_houdini_session(settings, parent_item)

        # remember if we collect any alembic/mantra nodes
        self._alembic_nodes_collected = False
        self._mantra_nodes_collected = False
        self._arnold_nodes_collected = False
        self._renderman_nodes_collected = False

        # methods to collect tk alembic/mantra/cache nodes if the app is installed
        self.collect_tk_alembicnodes(item)
        self.collect_tk_mantranodes(item)
        self.collect_tk_arnoldnodes(item)
        self.collect_tk_rendermannodes(item)
        self.collect_tk_cachenodes(item)
        self.collect_tk_usdropnodes(item)

        # collect other, non-toolkit outputs to present for publishing
        self.collect_node_outputs(item)

    def collect_current_houdini_session(self, settings, parent_item):
        """
        Creates an item that represents the current houdini session.
        :param dict settings: Configured settings for this collector
        :param parent_item: Parent Item instance
        :returns: Item of type houdini.session
        """

        publisher = self.parent

        # get the path to the current file
        path = hou.hipFile.path()

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Houdini Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item(
            "houdini.session", "Houdini File", display_name
        )

        # get the icon path to display for this item
        icon_path = os.path.join(self.disk_location, os.pardir, "icons", "houdini.png")
        session_item.set_icon_from_path(icon_path)

        # if a work template is defined, add it to the item properties so that
        # it can be used by attached publish plugins
        work_template_setting = settings.get("Work Template")
        if work_template_setting:
            work_template = publisher.engine.get_template_by_name(
                work_template_setting.value
            )

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            session_item.properties["work_template"] = work_template
            self.logger.debug("Work template defined for Houdini collection.")

        self.logger.info("Collected current Houdini session")
        return session_item

    def collect_node_outputs(self, parent_item):
        """
        Creates items for known output nodes
        :param parent_item: Parent Item instance
        """

        for node_category in _HOUDINI_OUTPUTS:
            for node_type in _HOUDINI_OUTPUTS[node_category]:

                if node_type == "alembic" and self._alembic_nodes_collected:
                    self.logger.debug(
                        "Skipping regular alembic node collection since tk "
                        "alembic nodes were collected. "
                    )
                    continue

                if node_type == "ifd" and self._mantra_nodes_collected:
                    self.logger.debug(
                        "Skipping regular mantra node collection since tk "
                        "mantra nodes were collected. "
                    )
                    continue

                path_parm_name = _HOUDINI_OUTPUTS[node_category][node_type]

                # get all the nodes for the category and type
                nodes = hou.nodeType(node_category, node_type).instances()

                # iterate over each node
                for node in nodes:

                    # get the evaluated path parm value
                    path = node.parm(path_parm_name).eval()

                    # ensure the output path exists
                    if not os.path.exists(path):
                        continue

                    self.logger.info(
                        "Processing %s node: %s" % (node_type, node.path())
                    )

                    # allow the base class to collect and create the item. it
                    # should know how to handle the output path
                    item = super(HoudiniSessionCollector, self)._collect_file(
                        parent_item, path, frame_sequence=True
                    )

                    # the item has been created. update the display name to
                    # include the node path to make it clear to the user how it
                    # was collected within the current session.
                    item.name = "%s (%s)" % (item.name, node.path())

    def collect_tk_cachenodes(self, parent_item):
        """
        Checks for an installed `tk-houdini-cache` app. If installed, will
        search for instances of the node in the current session and create an
        item for each one with an output on disk.
        :param parent_item: The item to parent new items to.
        """

        publisher = self.parent
        engine = publisher.engine

        cachenode_app = engine.apps.get("tk-houdini-cachenode")
        if not cachenode_app:
            self.logger.debug(
                "The tk-houdini-cachenode app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        try:
            tk_cache_nodes = cachenode_app.get_nodes()
        except AttributeError:
            self.logger.warning(
                "Unable to query the session for tk-houdini-cachenode " "instances."
            )
            return

        # retrieve the work file template defined by the app. we'll set this
        # on the collected cachenode items for use during publishing.
        work_template = cachenode_app.get_work_file_template()
        publish_template = cachenode_app.get_publish_file_template()

        for node in tk_cache_nodes:

            out_path = cachenode_app.get_output_path(node)

            self.logger.debug("out_path is %s" % (out_path))

            if not os.path.exists(out_path):
                self.logger.warning("out_path was not validated.")
                continue

            self.logger.info("Processing sgtk_cache node: %s" % (node.path(),))

            # allow the base class to collect and create the item. it
            # should know how to handle the output path
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, out_path, frame_sequence=True
            )

            # the item has been created. update the display name to
            # include the node path to make it clear to the user how it
            # was collected within the current session.
            item.name = "%s (%s)" % (item.name, node.path())

            if work_template:
                item.properties["work_template"] = work_template
                self.logger.info("Set work_template property on %s" % (node))
            else:
                self.logger.warning(
                    "Could not set work_template property. Will start versioning at 1."
                )

            if publish_template:
                item.properties["publish_template"] = publish_template
                self.logger.info("Set publish_template property on %s" % (node))
            else:
                self.logger.warning(
                    "Could not set publish_template property. Will use working template as output."
                )

    def collect_tk_usdropnodes(self, parent_item):
        """
        Checks for an installed `tk-houdini-usdrop` app. If installed, will
        search for instances of the node in the current session and create an
        item for each one with an output on disk.
        :param parent_item: The item to parent new items to.
        """

        publisher = self.parent
        engine = publisher.engine

        usdrop_app = engine.apps.get("tk-houdini-usdrop")
        if not usdrop_app:
            self.logger.debug(
                "The tk-houdini-usdrop node app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        tk_usdrop_nodes = usdrop_app.get_nodes()

        # retrieve the work file template defined by the app. we'll set this
        # on the collected USD rop node items for use during publishing.
        work_template = usdrop_app.get_work_file_template()
        publish_template = usdrop_app.get_publish_file_template()

        for node in tk_usdrop_nodes:

            output_path = usdrop_app.get_output_path(node)

            self.logger.debug("out_path is %s" % (output_path))

            if not os.path.exists(output_path):
                self.logger.warning("out_path was not validated.")
                continue

            self.logger.info("Processing sgtk_usdrop node: %s" % (node.path(),))

            # allow the base class to collect and create the item. it
            # should know how to handle the output path
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, output_path, frame_sequence=False
            )

            # get the icon path to display for this item
            icon_path = os.path.join(self.disk_location, os.pardir, "icons", "usd.png")
            item.set_icon_from_path(icon_path)

            # the item has been created. update the display name to
            # include the node path to make it clear to the user how it
            # was collected within the current session.
            item.name = "%s (%s)" % (item.name, node.path())

            if work_template:
                item.properties["work_template"] = work_template
                self.logger.info("Set work_template property on %s" % (node))
            else:
                self.logger.warning(
                    "Could not set work_template property. Will start versioning at 1."
                )

            if publish_template:
                item.properties["publish_template"] = publish_template
                self.logger.info("Set publish_template property on %s" % (node))
            else:
                self.logger.warning(
                    "Could not set publish_template property. Will use working template as output."
                )

    def collect_tk_alembicnodes(self, parent_item):
        """
        Checks for an installed `tk-houdini-alembicnode` app. If installed, will
        search for instances of the node in the current session and create an
        item for each one with an output on disk.
        :param parent_item: The item to parent new items to.
        """

        publisher = self.parent
        engine = publisher.engine

        alembicnode_app = engine.apps.get("tk-houdini-alembicnode")
        if not alembicnode_app:
            self.logger.debug(
                "The tk-houdini-alembicnode app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        try:
            tk_alembic_nodes = alembicnode_app.get_nodes()
        except AttributeError:
            self.logger.warning(
                "Unable to query the session for tk-houdini-alembicnode "
                "instances. It looks like perhaps an older version of the "
                "app is in use which does not support querying the nodes. "
                "Consider updating the app to allow publishing their outputs."
            )
            return

        # retrieve the work file template defined by the app. we'll set this
        # on the collected alembicnode items for use during publishing.
        work_template = alembicnode_app.get_work_file_template()

        for node in tk_alembic_nodes:

            out_path = alembicnode_app.get_output_path(node)

            if not os.path.exists(out_path):
                continue

            self.logger.info("Processing sgtk_alembic node: %s" % (node.path(),))

            # allow the base class to collect and create the item. it
            # should know how to handle the output path
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, out_path
            )

            # the item has been created. update the display name to
            # include the node path to make it clear to the user how it
            # was collected within the current session.
            item.name = "%s (%s)" % (item.name, node.path())

            if work_template:
                item.properties["work_template"] = work_template

            self._alembic_nodes_collected = True

    def collect_tk_mantranodes(self, parent_item):
        """
        Checks for an installed `tk-houdini-mantranode` app. If installed, will
        search for instances of the node in the current session and create an
        item for each one with an output on disk.
        :param parent_item: The item to parent new items to.
        """

        publisher = self.parent
        engine = publisher.engine

        mantranode_app = engine.apps.get("tk-houdini-mantranode")
        if not mantranode_app:
            self.logger.debug(
                "The tk-houdini-mantranode app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        try:
            tk_mantra_nodes = mantranode_app.get_nodes()
        except AttributeError:
            self.logger.warning(
                "Unable to query the session for tk-houdini-mantranode "
                "instances. It looks like perhaps an older version of the "
                "app is in use which does not support querying the nodes. "
                "Consider updating the app to allow publishing their outputs."
            )
            return

        # retrieve the work file template defined by the app. we'll set this
        # on the collected alembicnode items for use during publishing.
        work_template = mantranode_app.get_work_file_template()

        for node in tk_mantra_nodes:

            out_path = mantranode_app.get_output_path(node)

            if not os.path.exists(out_path):
                continue

            self.logger.info("Processing sgtk_mantra node: %s" % (node.path(),))

            # allow the base class to collect and create the item. it
            # should know how to handle the output path
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, out_path, frame_sequence=True
            )

            # the item has been created. update the display name to
            # include the node path to make it clear to the user how it
            # was collected within the current session.
            item.name = "%s (%s)" % (item.name, node.path())

            if work_template:
                item.properties["work_template"] = work_template

            self._mantra_nodes_collected = True

    def collect_tk_arnoldnodes(self, parent_item):
        # check if arnold app is installed and get all written-to-disk outputs

        publisher = self.parent
        engine = publisher.engine

        # check if arnold app is installed
        app = engine.apps.get("tk-houdini-arnold")
        if not app:
            self.logger.debug(
                "The tk-houdini-arnold app is not installed. Skipping collection of those nodes."
            )
            return

        htoa_env = os.getenv("HTOA")
        if not htoa_env:
            self.logger.debug(
                "Arnold is not loaded. Skipping collection of Arnold nodes."
            )
            return

        # collect all node instances
        try:
            nodes = app.handler.getNodes()
        except Exception as e:
            self.logger.error("Could not receive arnold node instances. %s" % str(e))

        work_template = app.get_work_file_template()
        publish_template = app.get_publish_file_template()

        frame_range = hou.playbar.playbackRange()
        first_frame = int(frame_range[0])
        last_frame = int(frame_range[1])

        # run collection on every node instance found
        for node in nodes:

            out_path = app.handler.getOutputPath(node)

            if not os.path.exists(out_path):
                continue

            self.logger.info("Processing sgtk_arnold node: %s" % node.path())

            # create the actual sub-item
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, out_path, frame_sequence=True
            )

            # item created, update gui
            item.name = "Beauty Render (%s)" % (node.path())

            # update item with work_template for later fields use
            item.properties["work_template"] = work_template
            item.properties["publish_template"] = publish_template
            item.properties["first_frame"] = first_frame
            item.properties["last_frame"] = last_frame

            self.logger.info(
                "Setting publish name to %s"
                % (publisher.util.get_publish_name(out_path, sequence=True))
            )

            # run for aovs
            self.__collect_tk_arnoldaovs(node, item, app, work_template)

            self._arnold_nodes_collected = True

    def __collect_tk_arnoldaovs(self, node, parent_item, app, work_template):
        # creates items for every enabled aov
        publisher = self.parent

        # get aov enable parameters
        parms = app.handler.getDifferentFileAOVs(node)
        aovs = {}

        for parm in parms:
            parmNumber = parm.name().replace("ar_aov_separate", "")
            if parm.eval():
                aovName = node.parm("ar_aov_label%s" % (parmNumber)).eval()
                aovs[aovName] = node.parm("ar_aov_separate_file%s" % parmNumber).eval()

        for aov in aovs.items():
            if not os.path.exists(aov[1]):
                continue

            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, aov[1], frame_sequence=True
            )

            # sub-item created, update gui
            item.name = "%s AOV Render" % (aov[0])

            # add worktemplate to every subitem
            if work_template:
                item.properties["work_template"] = work_template

            self.logger.info(
                "Setting publish name to %s"
                % (publisher.util.get_publish_name(aov[1], sequence=True))
            )

    def collect_tk_rendermannodes(self, parent_item):
        # This function will check all the SGTK RenderMan nodes (in Solaris) for files,
        # and if found, add them to the collector

        # Get Engine and Publisher
        publisher = self.parent
        engine = publisher.engine

        # Check if RenderMan app is installed
        app = engine.apps.get("tk-houdini-renderman")
        if not app:
            self.logger.debug(
                "The tk-houdini-renderman app is not installed. Skipping collection of those nodes."
            )
            return

        # Make sure to only execute the collector when RenderMan is loaded
        rman_env = os.getenv("RMANTREE")
        if not rman_env:
            self.logger.debug(
                "RenderMan is not loaded. Skipping collection of RenderMan nodes."
            )
            return

        # Get all the RenderMan node instances, if no found, skip collector
        try:
            nodes = app.get_all_renderman_nodes()
        except Exception as e:
            self.logger.error("Could not receive renderman node instances. %s" % str(e))
            return

        # Get the work file template from the app
        work_template = app.get_work_template()
        publish_template = app.get_publish_template()

        frame_range = hou.playbar.playbackRange()
        first_frame = int(frame_range[0])
        last_frame = int(frame_range[1])

        # Iterate trough every node that has been found
        for node in nodes:

            # Get the output path on the RenderMan node
            output_path = app.get_output_path(node)

            # Check if there is an output path
            if len(output_path) > 0:
                # If no output path found, skip collector
                if not os.path.exists(output_path):
                    continue

                # Make sure file has not already been published
                if not app.handler.get_published_status(node):
                    self.logger.info("Processing sgtk_hdprman node: %s" % node.path())

                    # Create the item to publish
                    item = super(HoudiniSessionCollector, self)._collect_file(
                        parent_item, output_path, frame_sequence=True
                    )

                    # Set the name for the publisher UI
                    render_name = app.get_render_name(node)
                    node_path = os.path.basename(node.path())
                    item.name = "Render (%s)" % render_name + ", " + node_path

                    # Add the work template to the list
                    item.properties["work_template"] = work_template
                    item.properties["publish_template"] = publish_template
                    item.properties["first_frame"] = first_frame
                    item.properties["last_frame"] = last_frame

                    # Generate the publish name, and set it
                    publish_name = publisher.util.get_publish_name(
                        output_path, sequence=True
                    )
                    self.logger.info("Setting publish name to %s" % publish_name)
                    item.properties.publish_name = publish_name

                    # Check all the filter parameters for files
                    self.__collect_tk_rendermanfilters(node, item, app, work_template)

                    # Return a true value because files have been found
                    self._renderman_nodes_collected = True

    def __collect_tk_rendermanfilters(self, node, parent_item, app, work_template):
        # This function will scan every filter that is activated for files,
        # and if files found, add them to the collector
        publisher = self.parent

        # Get all the filter parameters that have been set
        filters = app.handler.get_filters_output(node)

        # Iterate trough
        for filter in filters:
            filter_name = filter.get("name")
            filter_path = filter.get("path")
            if not os.path.exists(filter_path):
                continue

            subitem = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, filter_path, frame_sequence=True
            )

            # sub-item created, update gui
            subitem.name = filter_name

            # add worktemplate to every subitem
            if work_template:
                subitem.properties["work_template"] = work_template

            sub_publish_name = publisher.util.get_publish_name(
                filter_path, sequence=True
            )

            self.logger.info("Setting publish name to %s" % sub_publish_name)

            subitem.properties.publish_name = sub_publish_name
