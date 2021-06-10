import time

from mycroft.util.log import LOG


class Conversation:
    def __init__(self, script_meta=None, script_filename=None):
        # initialize static protected globals
        self._script_meta = script_meta if isinstance(script_meta, dict) else dict()        # Parser metadata
        self._script_filename = script_filename                                             # Script filename

        # Initialize static protected time variables
        self._script_start_time = int(time.time())                                          # Epoch time of script start

        # initialize script globals
        self.timeout = -1               # Timeout in seconds before executing timeout_action (max 3600, -1 indefinite)
        self.timeout_action = ''        # String to speak when timeout is reached (before exit dialog)
        self.variables = {},            # Dict of declared variables and values
        self.speaker_data = {},         # Language defined in script
        self.loops_dict = {}            # Dict of loop names and associated dict of values
        self.formatted_script = []      # List of script line dictionaries (excludes empty and comment lines)
        self.goto_tags = {}             # Dict of script tags and associated indexes

        # Initialize time variables
        self.line = ''                              # Current formatted_file Line being loaded (includes empty and comment lines)
        self.user_language = None                   # User language setting (not script setting)
        self.last_variable = None                   # Last variable read from the script (used to handle continuations)
        self.synonym_command = None                 # Command to execute when a synonym is heard (run script)
        self.synonyms = []                          # List of synonyms available to run the script

        # Initialize runtime variables
        self.current_index = 1          # Current formatted_script index being parsed or executed
        self.last_indent = 0            # Indentation of last line executed (^\s%4)
        self.variable_to_fill = ''      # Name of variable to which next input is assigned
        self.last_request = ''          # Identifier of last speak/execute emit to catch the response
        self.sub_string_counters = {}   # Counters associated with each string substitution option
        self.audio_responses = {}       # Dict of variables and associated audio inputs (file paths)

        # Initialize persistence variables
        self.pending_scripts = []       # List of pending script dicts

    # properties for protected attributes
    @property
    def script_meta(self):
        return self._script_meta

    @property
    def script_filename(self):
        return self._script_filename

    @property
    def script_start_time(self):
        return self._script_start_time

    # Methods to emulate dicts
    def __getitem__(self, item):
        return self.__getattribute__(item)

    def __setitem__(self, key, value):
        if key.startswith("_"):
            raise AttributeError("Cannot set a protected or private attribute")
        else:
            # TODO: should we force a type check? e.g. variables have to be always be a dict
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

    def get(self, item, default=None):
        try:
            return self.__getitem__(item)
        except AttributeError:
            return default

    # custom-conversations methods
    def to_json(self):
        """
        Return a JSON serializable representation of the object
        :return: dict with the object attributes
        """
        return self.__dict__

    def reset_values(self):
        """
        Resets dynamic attributes to their default values
        :return:
        """
        # reset script globals
        self.timeout = -1               # Timeout in seconds before executing timeout_action (max 3600, -1 indefinite)
        self.timeout_action = ''        # String to speak when timeout is reached (before exit dialog)
        self.variables = {},            # Dict of declared variables and values
        self.speaker_data = {},         # Language defined in script
        self.loops_dict = {}            # Dict of loop names and associated dict of values
        self.formatted_script = []      # List of script line dictionaries (excludes empty and comment lines)
        self.goto_tags = {}             # Dict of script tags and associated indexes

        # reset time variables
        self.line = ''                  # Current formatted_file Line being loaded (includes empty and comment lines)
        self.user_language = None       # User language setting (not script setting)
        self.last_variable = None       # Last variable read from the script (used to handle continuations)
        self.synonym_command = None     # Command to execute when a synonym is heard (run script)
        self.synonyms = []              # List of synonyms available to run the script

        # reset runtime variables
        self.current_index = 1          # Current formatted_script index being parsed or executed
        self.last_indent = 0            # Indentation of last line executed (^\s%4)
        self.variable_to_fill = ''      # Name of variable to which next input is assigned
        self.last_request = ''          # Identifier of last speak/execute emit to catch the response
        self.sub_string_counters = {}   # Counters associated with each string substitution option
        self.audio_responses = {}       # Dict of variables and associated audio inputs (file paths)

        # reset persistence variables
        self.pending_scripts = []       # List of pending script dicts


class ConversationManager:
    def __init__(self, user=None):
        self.manager_id = time.time()       # Epoch time as a unique id
        self._conversation_stack = []       # A list with all pending and active Conversations ordered from first to last
        self._user = user                   # A user associated with this manager
        self.user_scope_variables = {}      # Dict of declared variables and values from all scripts

    def __len__(self):
        return len(self._conversation_stack)

    @property
    def conversation_stack(self):
        return self._conversation_stack

    @property
    def user(self):
        return self._user

    # @user.setter
    # def user(self, user):
    #     self._user = user

    def push(self, item: Conversation):
        """
        Push conversation on top of the stack
        :param item: Conversation to be pushed
        :return: None
        """
        if type(item) == Conversation:
            self._conversation_stack.append(item)
        else:
            raise TypeError

    def pop(self):
        """
        Remove the last conversation from the stack and return it
        :return: last conversation in the stack
        """
        try:
            last_conversation = self._conversation_stack.pop()
            if not isinstance(last_conversation, Conversation):
                # TODO should we return this value back to the stack or keep it removed?
                raise ValueError("Last item in stack in of the Conversation class")
            return last_conversation
        except IndexError:
            return None

    def get_current_conversation(self):
        """
        Get the last conversation in the manager stack
        :return: last conversation or None
        """
        try:
            current_conversation = self._conversation_stack[-1]
        except IndexError:
            LOG.warning(f"There are no active conversations!")
            return None
        else:
            if type(current_conversation) == Conversation:
                return current_conversation
            else:
                raise TypeError

    def update_user_scope(self, conversation: Conversation):
        """
        Update the user scope variables with data from the Conversation
        :param conversation: a Conversation object to update the scope with
        :return: None
        """
        script_name, script_variables = conversation.get("script_filename", str()), conversation.get("variables", dict())
        variables = {f"{script_name}.{key}": value for key, value in script_variables.items()}
        self.user_scope_variables.update(variables)

    def lookup_variable_in_conversation(self, variable):
        """
        Look up a variable in a specific conversation
        :param variable: a variable in format script_name.variable_name
        :return: a variable value for the variable
        """
        variable_value = None
        try:
            script_name, variable_name = variable.split(".")
        except ValueError:
            LOG.warning("Wrong variable format, use script_name.variable_name instead")
        else:
            for conversation in self._conversation_stack:
                if script_name == conversation["script_filename"]:
                    variable_value = conversation.get("variables").get(variable_name)
                    break
        return variable_value

    def lookup_user_scope(self, variable):
        """
        Look up a variable in the user scope
        :param variable: a variable to look up
        :return: a variable value for the variable
        """
        return self.user_scope_variables.get(variable)
