import logging
import pickle
import re
import time
from copy import deepcopy
from os import path
from pprint import pformat

from .version import __version__
LOG = logging.getLogger("neon_script_parser")


class ScriptParser:
    def __init__(self):
        self._default_gender = "female"
        self._default_language = "en-US"
        self._file_ext = "ncs"
        self._no_implicit_multiline = ("if", "else", "case", "loop", "goto", "tag", "@")
        self._variable_functions = ("select_one", "voice_input", "table_scrape", "random", "closest", "profile")
        self._version = __version__

        # Many of these do nothing, can be used for parser line validation or other pre-exec functions
        self._pre_parser_options = {
            "language": self._parse_language_option,
            "case": self._parse_case_option,
            "script": self._parse_header_option,
            "description": self._parse_header_option,
            "author": self._parse_header_option,
            "timeout": self._parse_header_option,
            "execute": self._parse_execute_option,
            "speak": self._parse_speak_option,
            "neon speak": self._parse_speak_option,
            "name speak": self._parse_speak_option,
            "sub_values": self._parse_substitute_option,
            "sub_key": self._parse_substitute_option,
            "exit": self._parse_exit_option,
            "variable": self._parse_variable_option,
            "loop": self._parse_loop_option,
            "synonym": self._parse_synonym_option,
            "python": self._parse_python_option,
            "claps": self._parse_clap_option,
            "if": self._parse_if_option,
            "else": self._parse_else_option,
            "goto": self._parse_goto_option,
            "tag": self._parse_goto_option,
            "@": self._parse_goto_option,
            "set": self._parse_set_option,
            "reconvey": self._parse_reconvey_option,
            "voice_input": self._parse_input_option,
            "email": self._parse_email_option,
            "run": self._parse_run_option
        }

    def _parse_script_file(self, file_path):
        """
        Primary entry point to parse the requested script
        :param file_path: Fully defined file_path to the text script file
        :return:
        """
        with open(file_path, "r") as f:
            raw_text = f.readlines()
        meta = {"cversion": self._version,
                "compiled": round(time.time()),
                "compiler": "Neon AI Script Parser",
                "title": None,
                "author": None,
                "description": "",
                "raw_file": "".join(raw_text)}

        active_dict = {
            # Script Globals
            "script_filename": None,    # Script filename
            "script_meta": meta,        # Parser metadata
            "timeout": -1,              # Timeout in seconds before executing timeout_action (-1 indefinite)
            "timeout_action": '',       # String to speak when timeout is reached (before exit dialog)
            "variables": {},            # Dict of declared variables and values
            "speaker_data": {},         # Language defined in script
            "loops_dict": {},           # Dict of loop names and associated dict of values
            "formatted_script": [],     # List of script line dictionaries (excludes empty and comment lines)
            "goto_tags": {},            # Dict of script tags and associated indexes

            # Load time Variables
            "line": '',                 # Current formatted_file Line being loaded (includes empty and comment lines)
            "user_language": None,      # User language setting (not script setting)
            "last_variable": None,      # Last variable read from the script (used to handle continuations)
            "synonym_command": None,    # Command to execute when a synonym is heard (run script)
            "synonyms": [],             # List of synonyms available to run the script
            "claps": {}                 # Clap data associated with script
        }

        cache_data = self._load_to_cache(active_dict, file_path, "Neon")
        cache_data.append(meta)
        LOG.info(pformat(cache_data[0]))
        LOG.info(f"language={cache_data[1]}")
        LOG.info(f"variables={cache_data[2]}")
        LOG.info(f"loops={cache_data[3]}")
        LOG.info(f"tags={cache_data[4]}")
        LOG.info(f"timeout_secs={cache_data[5]}")
        LOG.info(f"timeout_act={cache_data[6]}")
        LOG.info(f"synonyms={cache_data[7]}")
        LOG.info(f"claps={cache_data[8]}")
        LOG.info(f"meta={cache_data[9]}")

        return cache_data

    def parse_script_to_dict(self, file_path):
        return self._parse_script_file(file_path)

    def parse_script_to_file(self, input_path, output_path=None):
        cache_data = self._parse_script_file(input_path)

        if not output_path:
            output_dir = path.dirname(input_path)
            output_name = f"{path.splitext(path.basename(input_path))[0]}.{self._file_ext}"
            output_path = path.join(output_dir, output_name)
        with open(output_path, 'wb+') as cache_file:
            pickle.dump(cache_data, cache_file, protocol=pickle.HIGHEST_PROTOCOL)
        LOG.debug(output_path)
        return output_path

    def _load_to_cache(self, active_dict, file_to_run, user):
        """
        Load a new or modified skill file and save to cache (and self.active_conversations if associated with a user);
        called at script update or launch if script file is newer than cached version
        :param active_dict: active_dict for user (or temp one if just pre-loading a file).
                            Should contain script filename here (basename with no dir/ext)
        :param file_to_run: parsed name of the skill file
        :param user: user loading the skill file (or "Neon" if just pre-loading a file)
        """
        timer_start = time.time()
        try:
            # Open file
            with open(file_to_run, 'r', encoding='utf-8') as script_file:
                # Loop through each line of the script_file
                line_num = 0
                in_comment_block = False
                for active_dict["line"] in script_file:
                    # Parse line_number and text into line_data dict
                    line_num += 1
                    line_data = dict()
                    last_line = dict()
                    if len(active_dict["formatted_script"]) > 0:
                        last_line = active_dict["formatted_script"][-1]
                    line_data["line_number"] = line_num
                    text_content = str(active_dict["line"]).strip()
                    if ': ' in text_content:
                        # Parse out command from text
                        text_content = text_content.split(': ', 1)[1]
                    line_data["text"] = text_content.lstrip('.').lstrip()

                    # Parse out comment lines
                    if active_dict["line"].lstrip().startswith('"""') or active_dict["line"].lstrip().endswith('"""'):
                        if in_comment_block:
                            in_comment_block = False
                        else:
                            in_comment_block = True
                    if active_dict["line"].lstrip().lstrip('.').startswith("#") or in_comment_block:
                        continue
                    if active_dict["line"].strip() == "":
                        continue

                    # Parse indent level (count of 4-space indents, rounding down)
                    if active_dict["line"].startswith("."):
                        num_leading = len(active_dict["line"]) - len(active_dict["line"].lstrip('.'))
                    else:
                        active_dict["line"] = active_dict["line"].replace("\t", "    ")
                        num_leading = len(active_dict["line"]) - len(active_dict["line"].lstrip())
                    indent = int((num_leading - (num_leading % 4)) / 4)

                    # Log warning if indentation is incorrect
                    if num_leading % 4 != 0:
                        LOG.warning(f'indent error at {line_num} in {file_to_run}')

                    line_data["indent"] = indent

                    # Check for case statements
                    parent_cases = None
                    # If indent decreased and we have an active case, check if we've exited that case
                    if line_data["indent"] < last_line.get("indent", 0) and \
                            len(last_line["parent_case_indents"]) > 0 and \
                            line_data["indent"] != last_line["parent_case_indents"][-1] + 1:
                        LOG.debug(f"Outdented line")
                        parent_cases = deepcopy(last_line["parent_case_indents"][0:-1])
                    # Catch case condition
                    elif last_line.get("parent_case_indents", None) and \
                            line_data["indent"] == last_line["parent_case_indents"][-1] + 1:
                        line_data["command"] = "case"

                    # Loop through and find any options in the line
                    for option in self._pre_parser_options:
                        try:
                            # If the line declares an option, go parse it into our active_dict and update our line_data
                            line_txt = active_dict["line"].lower().lstrip('.').strip()
                            if line_txt.startswith(option) and \
                                    (':' in line_txt or line_txt.startswith('@')            # @ tag
                                     or not line_txt.replace(option, "").strip() or         # option only
                                     option == "loop" and "LOOP" in active_dict["line"] or  # loop definition
                                     line_txt.replace(option, "").startswith("(") or        # function
                                     line_txt.replace(option, "").startswith("{")):         # function (depreciated)
                                line_data["command"] = option
                                # try:
                                #     self._pre_parser_options[option](active_dict, line_data)
                                # except Exception as x:
                                #     LOG.error(x)
                                continue

                        except Exception as e:
                            LOG.error(e)
                            LOG.error(active_dict["line"])
                            LOG.error(option)
                            LOG.error(user)
                            LOG.error(line_data)

                    try:
                        # Check for cases in variable_functions
                        if not line_data.get("command", None):
                            for option in self._variable_functions:
                                if active_dict["line"].lower().lstrip().startswith(option):
                                    line_data["command"] = option
                        # Check if this is a parent-case option
                        if not line_data.get("command", None):
                            if parent_cases:
                                for indent in parent_cases:
                                    if line_data["indent"] == indent + 1:
                                        line_data["command"] = "case"
                                        LOG.debug("This is a case option")

                        # If no command in-lined and not a case, copy command from last line
                        if not line_data.get("command", None):
                            # Check for variable assignment
                            if "=" in line_data.get("text") and \
                                    line_data.get("text").split("=", 1)[0].strip() in active_dict["variables"]:
                                line_data["command"] = "set"
                            # Same or greater indentation as last line, inherit that command unless disallowed
                            elif line_data["indent"] >= last_line["indent"] \
                                    and last_line["command"] not in self._no_implicit_multiline:
                                line_data["command"] = last_line["command"]
                                if line_data["command"] == "variable" and active_dict["last_variable"]:
                                    var_to_update = active_dict["last_variable"]
                                    LOG.debug(var_to_update)
                                    LOG.debug(active_dict["variables"][var_to_update])

                                    # Append to variable (write if empty)
                                    if line_data["text"].rstrip(","):
                                        if active_dict["variables"][var_to_update]:
                                            active_dict["variables"][var_to_update] \
                                                .append(line_data["text"].rstrip(","))
                                        else:
                                            active_dict["variables"][var_to_update] = [line_data["text"]]
                                    else:
                                        LOG.warning(f"null value line: {line_data}")
                                    LOG.debug(active_dict["variables"][var_to_update])
                            # Invalid assignment, outdented from previous
                            else:
                                LOG.warning(f"No explicit command, try assuming set: {line_data}")
                                if "=" in line_data["text"]:
                                    line_data["command"] = "set"
                                else:
                                    LOG.error(f"No command found for: {line_data}")

                        # If we previously found parent_cases, write them out
                        if parent_cases:
                            LOG.debug(f"parent_cases {parent_cases}")
                            line_data["parent_case_indents"] = parent_cases
                        # If this line is a case statement, add it to the list
                        else:
                            line_data["parent_case_indents"] = deepcopy(last_line.get("parent_case_indents", []))
                            if line_data["command"] == "case" and \
                                    active_dict["line"].lower().lstrip().startswith("case"):
                                LOG.debug(f'append {indent} to cases')
                                line_data["parent_case_indents"].append(indent)

                        # Do any pre-cache static parsing
                        if line_data["command"] == "@":
                            line_data["command"] = "tag"

                        try:
                            LOG.debug(line_data["command"])
                            self._pre_parser_options[line_data["command"]](active_dict, line_data)
                        except Exception as x:
                            LOG.error(x)
                        # Write out line data
                        LOG.debug(f'write out line_data: {line_data}')
                        active_dict["formatted_script"].append(line_data)
                    except Exception as e:
                        LOG.error(e)
            # End Line loop

            # Log data from parsing
            LOG.info(f' Time to parse the file {time.time() - timer_start}')
        except FileNotFoundError as e:
            LOG.debug(e)
            return

        to_save_cache = [active_dict["formatted_script"],
                         active_dict["speaker_data"],
                         active_dict["variables"],
                         active_dict["loops_dict"],
                         active_dict["goto_tags"],
                         active_dict["timeout"],
                         active_dict["timeout_action"],
                         active_dict["synonyms"],
                         active_dict["claps"]]
        return to_save_cache

    @staticmethod
    def _parse_header_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing of header lines
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        LOG.debug(line_data)
        option = line_data["command"]
        value = line_data["text"].strip()
        if option == "timeout":
            if " " in value:
                timeout, action = value.split(" ", 1)
                active_dict["timeout"] = int(timeout)
                active_dict["timeout_action"] = action.strip().strip('"')
            else:
                value = int(value)
                active_dict["timeout"] = value
                active_dict["timeout_action"] = None
        elif option == "author":
            active_dict["script_meta"]["author"] = value
        elif option == "description":
            active_dict["script_meta"]["description"] += f"\n{value.strip()}"
        elif option == "script":
            active_dict["script_meta"]["title"] = value.strip()

    @staticmethod
    def _parse_goto_option(active_dict, line_data=None):
        """
        Finds tag lines and indexes them for use at runtime
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        LOG.debug(line_data)
        line_txt = str(line_data["text"]).strip()
        tag = None
        if line_txt.startswith('@'):
            tag = line_txt[1:]
        elif line_txt.lower().startswith("tag:"):
            tag = line_txt.split(':')[1].strip()

        line_num = line_data["line_number"]
        if tag and tag in active_dict["goto_tags"]:
            LOG.error(f"duplicate tag will be ignored! {line_data}")
        elif tag:
            active_dict["goto_tags"][tag] = line_num

    def _parse_language_option(self, active_dict, line_data=None):
        """
        Sets speaker_data parameter at script load time (doesn't change language here)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        LOG.debug(line_data)

        # Only handle the first Language line; ignore subsequent ones inside the script
        if not active_dict["speaker_data"].get("name", None):
            line = re.sub('"', '', str(line_data["text"])).split()
            LOG.debug(line)
            if "female" in line:
                line.remove("female")
                gender = "female"
            elif "male" in line:
                line.remove("male")
                gender = "male"
            else:
                LOG.warning("No gender specified in Language line!")
                try:
                    gender = self._default_gender
                    LOG.debug(f"Got user preferred gender: {gender}")
                except Exception as e:
                    LOG.error(e)
                    gender = "female"

            LOG.debug(line)
            language = line[0].lower()

            active_dict["speaker_data"] = {"name": "Neon",
                                           "language": language,
                                           "gender": gender,
                                           "override_user": True}

    @staticmethod
    def _parse_variable_option(active_dict, line_data=None):
        """
        Loads variable names into `variables` at script load time (values are populated at runtime)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        LOG.debug(line_data)
        # Parse out variable name (key)
        if ':' in line_data["text"] and "{" in line_data["text"].split(':')[0] and \
                "}" in line_data["text"].split(':')[0]:  # Handle Variable: {name}: value  This syntax is depreciated
            key = line_data["text"].rstrip().split('{')[1].split("}")[0]
            line_data["text"] = line_data["text"].replace("{" + key + "}", key)
        elif "=" in line_data["text"]:  # Handle Variable: name = value
            key, value = line_data["text"].split('=', 1)
            if "{" in key:  # Variable: {name} = value
                key = key.split('{', 1)[1].split('}', 1)[0]
            elif ":" in key:  # Variable: name = value
                key = key.split(':', 1)[1].strip()
            else:  # Catch surrounding quotes and whitespace
                key = key.strip('"').strip()
        elif len(line_data["text"].strip().split(" ", 1)) == 2:  # Handle Variable: name: value/Variable: name = value
            LOG.debug(line_data["text"].strip().split(" ", 1))
            key, remainder = line_data["text"].replace(':', '').strip().split(" ", 1)
        else:  # Handle Variable: name
            LOG.debug(line_data["text"])
            key = line_data["text"].replace(':', '').strip()

        if "{" in key or "}" in key:
            key = key.split('{')[1].split('}')[0]
        LOG.debug(f"key={key}")
        active_dict["last_variable"] = key

        # This is a literal value, just parse it in
        if key not in active_dict["variables"].keys():
            LOG.debug(f"adding variable: {key}")
            active_dict["variables"][key] = None

    @staticmethod
    def _parse_loop_option(active_dict, line_data=None):
        """
        Parses loops into `loops_dict` at script load time
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        if str(active_dict["line"]).lstrip().startswith("LOOP "):
            loop_parts = re.sub("\n", "", str(active_dict["line"]).lstrip()).split(' ')
            LOG.debug(loop_parts)
            loop_name = loop_parts[1]
            line_num = line_data.get("line_number", -1)

            # Create loop dict if not exists
            if loop_name not in active_dict["loops_dict"]:
                LOG.debug(f"Adding {loop_name} to loops_dict")
                active_dict["loops_dict"][loop_name] = dict()

            # This is a loop end with no conditional
            if "END" in loop_parts:
                LOG.debug(f"Loop END line {line_num}")
                active_dict["loops_dict"][loop_name]["end"] = line_num

            # This is a conditional loop end
            elif "UNTIL" in loop_parts:
                LOG.debug(f"Loop UNTIL line {line_num}")
                active_dict["loops_dict"][loop_name]["end"] = line_num
                LOG.debug(f"loop_parts: {loop_parts}")
                variable = loop_parts[3]
                if len(loop_parts) > 4:
                    value = loop_parts[5]
                else:
                    value = "True"
                LOG.debug(f"Loop variable={variable}")
                LOG.debug(f"Loop value={value}")
                active_dict["loops_dict"][loop_name]["end_variable"] = variable
                active_dict["loops_dict"][loop_name]["end_value"] = value

            # This is the beginning of a loop
            else:
                LOG.debug(f'start loop {loop_name} at {line_num}')
                active_dict["loops_dict"][loop_name]["start"] = line_num
            LOG.debug(f'loops_dict={active_dict["loops_dict"]}')

    @staticmethod
    def _parse_synonym_option(active_dict, line_data=None):
        """
        Loads synonyms and emits to add them to YML configuration at script load time
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        LOG.debug(line_data)
        # Parse invalid characters from synonym string
        synonyms = line_data["text"].translate({ord(c): None for c in '!@#$"'}) \
            .rstrip().replace(", ", ",")
        # Parse list of synonyms
        synonyms = synonyms.split(',') if ',' in synonyms else [synonyms]
        active_dict["synonyms"].extend(synonyms)

    @staticmethod
    def _parse_clap_option(active_dict, line_data=None):
        """
        Modifies yml to add specified number of claps to alias running this skill file at script load time
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        LOG.debug(line_data)
        num, act = line_data["text"].split(" ", 1)
        active_dict["claps"][num] = act

    @staticmethod
    def _parse_exit_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of exit lines (i.e. could check for unreachable code, etc.)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_python_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of python lines (i.e. could be used to validate code)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_case_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of case lines (i.e. could be used to check conditional is defined)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_if_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of if lines (i.e. could be used to check conditional is defined)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_else_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of else lines (i.e. could be used to check for preceding if)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_execute_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of execute lines
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        if not line_data["text"] or line_data["text"].strip() == "":
            LOG.warning(f"null execute: {line_data}")

    @staticmethod
    def _parse_speak_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of speak lines
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        # TODO: ssml validation, name speak param checking DM
        if not line_data["text"] or line_data["text"].strip() == "":
            LOG.warning(f"null speak: {line_data}")

    @staticmethod
    def _parse_substitute_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of substitution lines
        (i.e. could check for invalid variable pairs)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_set_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of set lines (i.e. could check if in variables, etc.)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_run_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of run lines (i.e. could validate script exists, etc.)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_reconvey_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of reconvey lines (i.e. could add placeholder variables, etc.)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_input_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of voice_input lines (i.e. could add placeholder variables, etc.)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass

    @staticmethod
    def _parse_email_option(active_dict, line_data=None):
        """
        Does any pre-execution parsing and validation of email lines (i.e. could check for subject, body, etc.)
        :param active_dict: (dict) parsed script
        :param line_data: dict of data associated with current line being parsed
        """
        pass