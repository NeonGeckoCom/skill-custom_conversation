class Conversation:
    def __init__(self):
        # initialize script globals
        self.script_meta = {}           # Parser metadata
        self.script_filename = None     # Script filename
        self.timeout = -1               # Timeout in seconds before executing timeout_action (max 3600, -1 indefinite)
        self.timeout_action = ''        # String to speak when timeout is reached (before exit dialog)
        self.variables = {},            # Dict of declared variables and values
        self.speaker_data = {},         # Language defined in script
        self.loops_dict = {}            # Dict of loop names and associated dict of values
        self.formatted_script = []      # List of script line dictionaries (excludes empty and comment lines)
        self.goto_tags = {}             # Dict of script tags and associated indexes

        # Initialize time variables
        self.line = ''                  # Current formatted_file Line being loaded (includes empty and comment lines)
        self.user_language = None       # User language setting (not script setting)
        self.last_variable = None       # Last variable read from the script (used to handle continuations)
        self.synonym_command = None     # Command to execute when a synonym is heard (run script)
        self.synonyms = []              # List of synonyms available to run the script
        self.script_start_time = None   # Epoch time of script start

        # Initialize runtime variables
        self.current_index = 0          # Current formatted_script index being parsed or executed
        self.last_indent = 0            # Indentation of last line executed (^\s%4)
        self.variable_to_fill = ''      # Name of variable to which next input is assigned
        self.last_request = ''          # Identifier of last speak/execute emit to catch the response
        self.sub_string_counters = {}   # Counters associated with each string substitution option
        self.audio_responses = {}       # Dict of variables and associated audio inputs (file paths)

        # Initialize persistence variables
        self.pending_scripts = []       # List of pending script dicts

    # Methods to emulate dicts
    def __getitem__(self, item):
        return self.__getattribute__(item)

    def __setitem__(self, key, value):
        self.__setattr__(key, value)

    def __contains__(self, item):
        return True if hasattr(self, item) else False

    def __str__(self):
        return str(self.__dict__)

    def __repr__(self):
        return repr(self.__dict__)

    def __len__(self):
        return len(self.__dict__)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def get(self, item, other=None):
        try:
            return self.__getitem__(item)
        except AttributeError:
            return other

    def to_json(self):
        """
        Return a JSON serializable representation of the object
        :return: dict with the object attributes
        """
        return self.__dict__


class ConversationManager:
    def __init__(self):
        pass