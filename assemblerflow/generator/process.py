import os
import jinja2
import logging

from os.path import dirname, join, abspath

logger = logging.getLogger("main.{}".format(__name__))


class Process:
    """Main interface for basic process functionality

    The ``Process`` class is intended to be inherited by specific process
    classes (e.g., :py:class:`IntegrityCoverage`) and provides the basic
    functionality to build the channels and links between processes.

    Child classes are expected to inherit the ``__init__`` execution, which
    basically means that at least, the child must be defined as::

        class ChildProcess(Process):
            def__init__(self, **kwargs):
                super().__init__(**kwargs)

    This ensures that when the ``ChildProcess`` class is instantiated, it
    automatically sets the attributes of the parent class.

    This also means that child processes must be instantiated providing
    information on the process type and jinja2 template with the nextflow code.

    Parameters
    ----------
    ptype : str
        Process type. See :py:attr:`Process.accepted_types`.
    template : str
        Name of the jinja2 template with the nextflow code for that process.
        Templates are stored in ``generator/templates``.
    """

    RAW_MAPPING = {
        "fastq": {
            "params": "fastq",
            "channel": "IN_fastq_raw",
            "channel_str": "IN_fastq_raw = Channel.fromFilePairs(params.fastq)"
        },
        "assembly": {
            "params": "fasta",
            "channel": "IN_fasta_raw",
            "channel_str": "IN_fasta_raw = Channel.fromFilePairs(params.fasta)"
        }
    }
    """
    dict: Contains the mapping between the :attr:`Process.input_type` attribute
    and the corresponding nextflow parameter and main channel definition, e.g.::

        "fastq" : {
            "params": "fastq",
            "channel: "<channel>
        }
    """

    def __init__(self, template):

        self.pid = None
        """
        int: Process ID number that represents the order and position in the
        generated pipeline
        """

        self.template = template
        """
        str: Template name for the current process. This string will be used
        to fetch the file containing the corresponding jinja2 template
        in the :py:func:`_set_template` method
        """

        self._template_path = None
        """
        str: Path to the file containing the jinja2 template file. It's
        set in :py:func:`_set_template`.
        """
        self._set_template(template)

        self.input_type = None
        """
        str: Type of expected input data. Used to verify the connection between
        two processes is viable.
        """

        self.output_type = None
        """
        str: Type of output data. Used to verify the connection between
        two processes is viable.
        """

        self.ignore_type = False
        """
        boolean: If True, this process will ignore the input/output type
        requirements. This attribute is set to True for terminal singleton 
        forks in the pipeline. 
        """

        self.ignore_pid = False
        """
        boolean: If True, this process will not make the pid advance. This
        is used for terminal forks before the end of the pipeline.
        """

        self.dependencies = []
        """
        list: Contains the dependencies of the current process in the form
        of the :py:attr:`Process.template` attribute (e.g., [``fastqc``])
        """

        self.lane = None
        self.parent_lane = None

        self.input_channel = None
        """
        str: Place holder of the main input channel for the current process.
        This attribute can change dynamically depending on the forks and
        secondary channels in the final pipeline.
        """

        self.output_channel = None
        """
        str: Place holder of the main output channel for the current process.
        This attribute can change dynamically depending on the forks and
        secondary channels in the final pipeline.
        """

        self.input_user_channel = None
        """
        dict: Stores a dictionary of two key:value pairs containing
        the raw input channel for the process. This is automatically
         determined by the :attr:`~Process.input_type` attribute, and will
        fetch the information that is mapped in the :attr:`RAW_MAPPING`
         variable. It will only be used by the first process(es) defined in
         a pipeline. 
        """

        self.link_start = []
        """
        list: List of strings with the starting points for secondary channels.
        When building the pipeline, these strings will be matched with equal
        strings in the :py:attr:`link_end` attribute of other Processes.
        """

        self.link_end = []
        """
        list: List of dictionaries containing the a string of the ending point
        for a secondary channel. Each dictionary should contain at least
        two key/vals:
        ``{"link": <link string>, "alias":<string for template>}``
        """

        self.status_channels = ["STATUS"]
        """
        list: Name of the status channels produced by the process. By default,
        it sets a single status channel. If more than one status channels
        are required for the process, list each one in this attribute
        (e.g., :py:attr:`FastQC.status_channels`)
        """
        self.status_strs = []
        """
        str: Name of the status channel for the current process. These strings
        will be provided to the StatusCompiler process to collect and
        compile status reports
        """

        self.forks = []
        """
        list: List of strings with the literal definition of the forks for
        the current process, ready to be added to the template string.
        """
        self.main_forks = []
        """
        list: List of the channels onto which the main output should be
        forked into. They will be automatically added to the
        :attr:`~Process.main_forks` attribute when setting the secondary
        channels
        """

        self.secondary_inputs = []
        self.secondary_input_str = ""

        self._context = None
        """
        dict: Dictionary with the keyword placeholders for the string template
        of the current process.
        """

    def _set_template(self, template):
        """Sets the path to the appropriate jinja template file

        When a Process instance is initialized, this method will fetch
        the location of the appropriate template file, based on the
        ``template`` argument. It will raise an exception is the template
        file is not found. Otherwise, it will set the
        :py:attr:`Process.template_path` attribute.
        """

        # Set template directory
        tpl_dir = join(dirname(abspath(__file__)), "templates")

        # Set template file path
        tpl_path = join(tpl_dir, template + ".nf")

        if not os.path.exists(tpl_path):
            raise Exception("Template {} does not exist".format(tpl_path))

        self._template_path = join(tpl_dir, template + ".nf")

    def set_main_channel_names(self, input_suffix, output_suffix, lane):
        """Sets the main channel names based on the input and output lanes
        of the process. This is performed when connecting processes.

        Parameters
        ----------
        input_lane : int
            Lane of the previous process, so that it's output channel
            matches with the input of this channel
        output_lane : int
            Lane of the current channel, so that the output matches with the
            next lane.
        """

        self.input_channel = "{}_in_{}".format(self.template, input_suffix)
        self.output_channel = "{}_out_{}".format(self.template, output_suffix)
        self.lane = lane

    def get_user_channel(self):
        """Sets the main raw channels for the process

        This will set the :attr:`~Process._input_user_channel` attribute
        based on the :attr:`~Process.input_type` of the process. It retrieves
        the information from the :attr:`~Process.RAW_MAPPINGS` dictionary.
        If the input type is not present in the dictionary, it will set the
        attribute to None
        """

        res = {"input_channel": self.input_channel}

        if self.input_type in self.RAW_MAPPING:
            return {**res, **self.RAW_MAPPING[self.input_type]}

    @staticmethod
    def render(template, context):
        """Wrapper to the jinja2 render method from a template file

        Parameters
        ----------
        template : str
            Path to template file.
        context : dict
            Dictionary with kwargs context to populate the template
        """

        path, filename = os.path.split(template)

        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(path or './')
        ).get_template(filename).render(context)

    @property
    def template_str(self):
        """Class property that returns a populated template string

        This property allows the template of a particular process to be
        dynamically generated and returned when doing ``Process.template_str``.

        Returns
        -------
        x : str
            String with the complete and populated process template

        """

        if not self._context:
            raise Exception("Channels must be setup first using the "
                            "set_channels method")

        logger.debug("Setting context for template {}: {}".format(
            self.template, self._context
        ))

        x = self.render(self._template_path, self._context)
        return x

    def set_channels(self, **kwargs):
        """ General purpose method that sets the main channels

        This method will take a variable number of keyword arguments to
        set the :py:attr:`Process._context` attribute with the information
        on the main channels for the process. This is done by appending
        the process ID (:py:attr:`Process.pid`) attribute to the input,
        output and status channel prefix strings. In the output channel,
        the process ID is incremented by 1 to allow the connection with the
        channel in the next process.

        The ``**kwargs`` system for setting the :py:attr:`Process._context`
        attribute also provides additional flexibility. In this way,
        individual processes can provide additional information not covered
        in this method, without changing it.

        Parameters
        ----------
        kwargs : dict
            Dictionary with the keyword arguments for setting up the template
            context
        """

        self.pid = kwargs.get("pid")

        for i in self.status_channels:
            self.status_strs.append("{}_{}".format(i, self.pid))

        if self.main_forks:
            logger.debug("Setting main fork channels: {}".format(
                self.main_forks))
            operator = "set" if len(self.main_forks) == 1 else "into"
            self.forks.append("\n{}.{}{{ {} }}\n".format(
                self.output_channel, operator, ";".join(self.main_forks)))

        self._context = {**kwargs, **{"input_channel": self.input_channel,
                                      "output_channel": self.output_channel,
                                      "template": self.template,
                                      "forks": "\n".join(self.forks)}}

    def update_main_forks(self, sink):
        """Updates the forks attribute with the sink channel destination

        Parameters
        ----------
        sink : str
            Channel onto which the main input will be forked to

        """

        self.main_forks.append(sink)

    def set_secondary_channel(self, source, channel_list):
        """ General purpose method for setting a secondary channel

        This method allows a given source channel to be forked into one or
        more channels and sets those forks in the :py:attr:`Process.forks`
        attribute. Both the source and the channels in the ``channel_list``
        argument must be the final channel strings,  which means that this
        method should be called only after setting the main channels.

        If the source is not a main channel, this will simply create a fork
        or set for every channel in the ``channel_list`` argument list::

            SOURCE_CHANNEL_1.into{SINK_1;SINK_2}

        If the source is a main channel, this will apply some changes to
        the output channel of the process, to avoid overlapping main output
        channels.  For instance, forking the main output channel for process
        2 would create a ``MAIN_2.into{...}``. The issue here is that the
        ``MAIN_2`` channel is expected as the input of the next process, but
        now is being used to create the fork. To solve this issue, the output
        channel is modified into ``_MAIN_2``, and the fork is set to
        the channels provided channels plus the ``MAIN_2`` channel::

            _MAIN_2.into{MAIN_2;MAIN_5;...}

        Parameters
        ----------
        source : str
            String with the name of the source channel
        channel_list : list
            List of channels that will receive a fork of the secondary
            channel
        """

        logger.debug("Setting secondary channel for source '{}': {}".format(
            source, channel_list))

        # Handle the case where the main channel is forked
        if source.startswith("MAIN"):
            # Update previous output_channel to prevent overlap with
            # subsequent main channels. This is done by adding a "_" at the
            # beginning of the channel name
            self._context["output_channel"] = "_{}".format(
                self._output_channel)
            # Set source to modified output channel
            source = self._context["output_channel"]
            # Add the next first main channel to the channel_list
            channel_list.append(self._output_channel)
        # Handle forks from non main channels
        else:
            source = "{}_{}".format(source, self.pid)

        # Removes possible duplicate channels, when the fork is terminal
        channel_list = list(set(channel_list))

        # When there is only one channel to fork into, use the 'set' operator
        # instead of 'into'
        if len(channel_list) == 1:
            self.forks.append("\n{}.set{{ {} }}\n".format(source,
                                                           channel_list[0]))
        else:
            self.forks.append("\n{}.into{{ {} }}\n".format(
                source, ";".join(channel_list)))

        logger.debug("Setting forks attribute to: {}".format(self.forks))
        self._context = {**self._context, **{"forks": "\n".join(self.forks)}}


class Status(Process):
    """Extends the Process methods to status-type processes
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

    def set_status_channels(self, channel_list):
        """General method for setting the input channels for the status process

        Given a list of status channels that are gathered during the pipeline
        construction, this method will automatically set the input channel
        for the status process. This makes use of the ``mix`` channel operator
        of nextflow for multiple channels::

            STATUS_1.mix(STATUS_2,STATUS_3,...)

        This will set the ``status_channels`` key for the ``_context``
        attribute of the process.

        Parameters
        ----------
        channel_list : list
            List of strings with the final name of the status channels
        """

        if len(channel_list) == 1:
            logger.debug("Setting only one status channel: {}".format(
                channel_list[0]))
            self._context = {"status_channels": channel_list[0]}

        else:
            first_status = channel_list[0]
            lst = ",".join(channel_list[1:])

            s = "{}.mix({})".format(first_status, lst)

            logger.debug("Status channel string: {}".format(s))

            self._context = {"status_channels": s}


class Init(Process):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = None
        self.output_type = "raw"

        self.status_channels = []

    def set_raw_inputs(self, raw_input):
        """

        Parameters
        ----------
        raw_input_list

        Returns
        -------

        """

        logger.debug("Setting raw inputs using raw input list: {}".format(
            raw_input))

        primary_inputs = []

        for el in raw_input.values():
            primary_inputs.append(el["channel_str"])
            if len(el["raw_forks"]) == 1:
                self.forks.append("\n{}.set{{ {} }}\n".format(
                    el["channel"], el["raw_forks"][0]
                ))
            else:
                self.forks.append("\n{}.into{{ {} }}\n".format(
                    el["channel"], ";".join(el["raw_forks"])
                ))

        logger.debug("Setting raw inputs: {}".format(primary_inputs))
        logger.debug("Setting forks attribute to: {}".format(self.forks))
        self._context = {**self._context,
                         **{"forks": "\n".join(self.forks),
                            "main_inputs": "\n".join(primary_inputs)}}


    def set_secondary_inputs(self, channel_dict):

        logger.debug("Setting secondary inputs: {}".format(channel_dict))

        secondary_input_str = "\n".join(list(channel_dict.values()))
        self._context = {**self._context,
                         **{"secondary_inputs": secondary_input_str}}


class IntegrityCoverage(Process):
    """Process template interface for first integrity_coverage process

    This process is set with:

        - ``input_type``: fastq
        - ``output_type``: fastq
        - ``ptype``: pre_assembly

    It contains two **secondary channel link starts**:

        - ``SIDE_phred``: Phred score of the FastQ files
        - ``SIDE_max_len``: Maximum read length
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "fastq"

        self._main_in_str = "MAIN_raw"

        self.secondary_inputs = [
            {
                "params": "genomeSize",
                "channel": "IN_genome_size = Channel.value(params.genomeSize)"
            },
            {
                "params": "minCoverage",
                "channel": "IN_min_coverage = "
                           "Channel.value(params.minCoverage)"
            }
        ]

        self.link_start.extend(["SIDE_phred", "SIDE_max_len"])


class SeqTyping(Process):
    """

    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = None

        self.ignore_type = True
        self.ignore_pid = True

        self.status_channels = []

        self.link_start = None
        self.link_end.append({"link": "MAIN_raw",
                              "alias": "SIDE_SeqType_raw"})


class PathoTyping(Process):
    """

    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = None

        self.ignore_type = True
        self.ignore_pid = True

        self.status_channels = []

        self.secondary_inputs = [
            {
                "params": "pathoSpecies",
                "channel": "IN_pathoSpecies = "
                           "Channel.value(params.pathoSpecies)"
            }
        ]

        self.link_start = None
        self.link_end.append({"link": "MAIN_raw",
                              "alias": "SIDE_PathoType_raw"})


class CheckCoverage(Process):
    """Process template interface for additional integrity_coverage process

    This process is set with:

        - ``input_type``: fastq
        - ``output_type``: fastq
        - ``ptype``: pre_assembly

    It contains one **secondary channel link start**:

        - ``SIDE_max_len``: Maximum read length

    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "fastq"

        self.secondary_inputs = [
            {
                "params": "genomeSize",
                "channel": "IN_genome_size = Channel.value(params.genomeSize)"
            },
            {
                "params": "minCoverage",
                "channel": "IN_min_coverage = "
                           "Channel.value(params.minCoverage)"
            }
        ]

        self.link_start.extend(["SIDE_max_len"])


class FastQC(Process):
    """FastQC process template interface

    This process is set with:

        - ``input_type``: fastq
        - ``output_type``: fastq
        - ``ptype``: pre_assembly

    It contains two **status channels**:

        - ``STATUS_fastqc``: Status for the fastqc process
        - ``STATUS_report``: Status for the fastqc_report process

    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "fastq"

        self.status_channels = ["STATUS_fastqc", "STATUS_report"]
        """
        list: Setting status channels for FastQC execution and FastQC report
        """

        self.secondary_inputs = [
            {
                "params": "adapters",
                "channel": "IN_adapters = Channel.value(params.adapters)"
            }
        ]


class Trimmomatic(Process):
    """Trimmomatic process template interface

    This process is set with:

        - ``input_type``: fastq
        - ``output_type``: fastq
        - ``ptype``: pre_assembly

    It contains one **secondary channel link end**:

        - ``SIDE_phred`` (alias: ``SIDE_phred``): Receives FastQ phred score
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "fastq"

        self.link_end.append({"link": "SIDE_phred", "alias": "SIDE_phred"})

        self.secondary_inputs = [
            {
                "params": "trimOpts",
                "channel": "IN_trimmomatic_opts = "
                           "Channel.value([params.trimSlidingWindow,"
                           "params.trimLeading,params.trimTrailing,"
                           "params.trimMinLength])"
            }
        ]


class FastqcTrimmomatic(Process):
    """Fastqc + Trimmomatic process template interface

    This process executes FastQC only to inform the trim range for trimmomatic,
    not for QC checks.

    This process is set with:

        - ``input_type``: fastq
        - ``output_type``: fastq
        - ``ptype``: pre_assembly

    It contains one **secondary channel link end**:

        - ``SIDE_phred`` (alias: ``SIDE_phred``): Receives FastQ phred score

    It contains three **status channels**:

        - ``STATUS_fastqc``: Status for the fastqc process
        - ``STATUS_report``: Status for the fastqc_report process
        - ``STATUS_trim``: Status for the trimmomatic process
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "fastq"

        self.link_end.append({"link": "SIDE_phred", "alias": "SIDE_phred"})

        self.status_channels = ["STATUS_fastqc", "STATUS_report",
                                "STATUS_trim"]

        self.secondary_inputs = [
            {
                "params": "adapters",
                "channel": "IN_adapters = Channel.value(params.adapters)"
            },
            {
                "params": "trimOpts",
                "channel": "IN_trimmomatic_opts = "
                           "Channel.value([params.trimSlidingWindow,"
                           "params.trimLeading,params.trimTrailing,"
                           "params.trimMinLength])"
            }
        ]


class Skesa(Process):
    """Skesa process template interface
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "assembly"


class Spades(Process):
    """Spades process template interface

    This process is set with:

        - ``input_type``: fastq
        - ``output_type``: assembly
        - ``ptype``: assembly

    It contains one **secondary channel link end**:

        - ``SIDE_max_len`` (alias: ``SIDE_max_len``): Receives max read length
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "fastq"
        self.output_type = "assembly"

        self.link_end.append({"link": "SIDE_max_len", "alias": "SIDE_max_len"})

        self.secondary_inputs = [
            {
                "params": "spadesOpts",
                "channel": "IN_spades_opts = Channel.value("
                           "[params.spadesMinCoverage,"
                           "params.spadesMinKmerCoverage])"
            },
            {
                "params": "spadesKmers",
                "channel": "IN_spades_kmers = "
                           "Channel.value(params.spadesKmers)"
            }
        ]


class ProcessSpades(Process):
    """Process spades process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: assembly
        - ``ptype``: post_assembly

    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = "assembly"

        self.secondary_inputs = [
            {
                "params": "processSpadesOpts",
                "channel": "IN_process_spades_opts = "
                           "Channel.value([params.spadesMinContigLen,"
                           "params.spadesMinKmerCoverage,"
                           "params.spadesMaxContigs])"
            }
        ]


class AssemblyMapping(Process):
    """Assembly mapping process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: assembly
        - ``ptype``: post_assembly

    It contains one **secondary channel link end**:

        - ``MAIN_fq`` (alias: ``_MAIN_assembly``): Receives the FastQ files
        from the last process with ``fastq`` output type.

    It contains two **status channels**:

        - ``STATUS_am``: Status for the assembly_mapping process
        - ``STATUS_amp``: Status for the process_assembly_mapping process
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = "assembly"

        self.status_channels = ["STATUS_am", "STATUS_amp"]

        self.link_start.append("SIDE_BpCoverage")
        self.link_end.append({"link": "MAIN_fq", "alias": "_MAIN_assembly"})

        self.secondary_inputs = [
            {
                "params": "assemblyMappingOpts",
                "channel": "IN_assembly_mapping_opts = "
                           "Channel.value([params.minAssemblyCoverage,"
                           "params.AMaxContigs])"
            }
        ]


class Pilon(Process):
    """Pilon mapping process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: assembly
        - ``ptype``: post_assembly

    It contains one **dependency process**:

        - ``assembly_mapping``: Requires the BAM file generated by the
        assembly mapping process
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = "assembly"

        self.dependencies = ["assembly_mapping"]

        self.link_end.append({"link": "SIDE_BpCoverage",
                              "alias": "SIDE_BpCoverage"})


class Mlst(Process):
    """Mlst mapping process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: None
        - ``ptype``: post_assembly

    It contains one **secondary channel link end**:

        - ``MAIN_assembly`` (alias: ``MAIN_assembly``): Receives the last
        assembly.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = "assembly"


class Abricate(Process):
    """Abricate mapping process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: None
        - ``ptype``: post_assembly

    It contains one **secondary channel link end**:

        - ``MAIN_assembly`` (alias: ``MAIN_assembly``): Receives the last
        assembly.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = None

        self.ignore_type = True

        self.link_start = None
        self.link_end.append({"link": "MAIN_assembly",
                              "alias": "MAIN_assembly"})


class Prokka(Process):
    """Prokka mapping process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: None
        - ``ptype``: post_assembly

    It contains one **secondary channel link end**:

        - ``MAIN_assembly`` (alias: ``MAIN_assembly``): Receives the last
        assembly.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = None

        self.ignore_type = True

        self.link_start = None
        self.link_end.append({"link": "MAIN_assembly",
                              "alias": "MAIN_assembly"})


class Chewbbaca(Process):
    """Prokka mapping process template interface

    This process is set with:

        - ``input_type``: assembly
        - ``output_type``: None
        - ``ptype``: post_assembly

    It contains one **secondary channel link end**:

        - ``MAIN_assembly`` (alias: ``MAIN_assembly``): Receives the last
        assembly.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.input_type = "assembly"
        self.output_type = None

        self.ignore_type = True

        self.link_start = None
        self.link_end.append({"link": "MAIN_assembly",
                              "alias": "MAIN_assembly"})


class TraceCompiler(Process):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.link_start = None

        self.ignore_type = True


class StatusCompiler(Status):
    """Status compiler process template interface

    This special process receives the status channels from all processes
    in the generated pipeline.

    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.ignore_type = True

        self.link_start = None

