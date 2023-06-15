# NEON AI (TM) SOFTWARE, Software Development Kit & Application Development System
#
# Copyright 2008-2021 Neongecko.com Inc. | All Rights Reserved
#
# Notice of License - Duplicating this Notice of License near the start of any file containing
# a derivative of this software is a condition of license for this software.
# Friendly Licensing:
# No charge, open source royalty free use of the Neon AI software source and object is offered for
# educational users, noncommercial enthusiasts, Public Benefit Corporations (and LLCs) and
# Social Purpose Corporations (and LLCs). Developers can contact developers@neon.ai
# For commercial licensing, distribution of derivative works or redistribution please contact licenses@neon.ai
# Distributed on an "AS IS” basis without warranties or conditions of any kind, either express or implied.
# Trademarks of Neongecko: Neon AI(TM), Neon Assist (TM), Neon Communicator(TM), Klat(TM)
# Authors: Guy Daniels, Daniel McKnight, Regina Bloomstine, Elon Gasper, Richard Leeds
#
# Specialized conversational reconveyance options from Conversation Processing Intelligence Corp.
# US Patents 2008-2021: US7424516, US20140161250, US20140177813, US8638908, US8068604, US8553852, US10530923, US10530924
# China Patent: CN102017585  -  Europe Patent: EU2156652  -  Patents Pending

import base64
import os
import shutil
import json
import re
import git
import random
import difflib
import datetime
import time

from copy import deepcopy
from adapt.intent import IntentBuilder
from git import InvalidGitRepositoryError

from mycroft.audio import wait_while_speaking
from ovos_bus_client import Message
from mycroft.skills.core import intent_handler
from neon_utils.message_utils import get_message_user, request_from_mobile, request_for_neon, build_message
from neon_utils.skills.neon_skill import NeonSkill
from neon_utils.user_utils import get_user_prefs
from neon_utils.web_utils import scrape_page_for_links as scrape
from neon_utils.parse_utils import clean_quotes
from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements
from mycroft.util.parse import normalize
from mycroft.util.audio_utils import play_audio_file

from .utils_emulate import Conversation, ConversationManager

# TIMEOUT = 8

# TODO: This or something like this to match a script name DM
# def find_closest(sorted_list, number_anchor):
#     # print(f"^^^^^^^^^^^^^^^^^^ {sorted_list} ^^^^ {number_anchor}")
#     sorted_list = sorted_list[:sorted_list.index(float(number_anchor))]
#     pos = bisect_left(sorted_list, float(number_anchor))
#     if pos == 0:
#         try:
#             return sorted_list[0]
#         except IndexError:
#             return '0.0'
#     if pos == len(sorted_list):
#         return sorted_list[-1]
#     before = sorted_list[pos - 1]
#     after = sorted_list[pos]
#     if float(after) - float(number_anchor) < float(number_anchor) - float(before):
#         return float(after)
#     else:
#         return float(before)


# def build_signal_name(user, text):
#     """
#     Generate a signal name for the given user and utterance
#     :param user: (str) user to create signal for
#     :param text: (str) signal text to check for
#     :return: (str) signal name to create
#     """
#     # strip non-alphanumeric chars from text
#     clean_text = re.sub('[^0-9a-zA-Z]+', '', text)
#     return f"{user}_CC_{clean_text}"


class CustomConversations(NeonSkill):
    __location__ = os.path.realpath(
        os.path.join(os.getcwd(), os.path.dirname(__file__)))

    def __init__(self, **kwargs):
        NeonSkill.__init__(self, **kwargs)

        self.file_ext = ".ncs"
        # TODO: Refactor to skill FS
        self.text_location = f"{self.__location__}/script_txt"
        self.audio_location = f"{self.__location__}/script_audio"
        self.transcript_location = f"{self.__location__}/script_transcript"

        # self.update_message = False
        self.reload_skill = False  # This skill should not be reloaded or else active users break
        self.runtime_execution, self.variable_functions = {}, {}
        self.perspective_changes = {"am": "are",
                                    "your": "my",
                                    "my": "your",
                                    "me": "you",
                                    "i": "you",
                                    "you": "i",
                                    "myself": "yourself",
                                    "yourself": "myself"}

        # Commands that should not carry over to subsequent lines implicitly
        self.no_implicit_multiline = ("if", "else", "case", "loop", "goto", "tag", "@")

        # Commands for which wildcards (*) should be replaced with unique variable names
        self.substitute_wildcards = ("sub_key", "sub_values")

        # Commands that exist in a script before executable code
        self.header_options = ("script", "description", "author", "timeout", "claps", "synonym")

        # If statement comparators
        self.string_comparators = ("IN", "CONTAINS", "STARTSWITH", "ENDSWITH")
        self.math_comparators = ("==", "!=", ">", "<", ">=", "<=")
        self.active_conversations = dict()
        self.awaiting_input = list()

        self.speak_timeout = 5
        self.response_timeout = 10

    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(network_before_load=True,
                                   internet_before_load=True,
                                   gui_before_load=False,
                                   requires_internet=True,
                                   requires_network=True,
                                   requires_gui=False,
                                   no_internet_fallback=True,
                                   no_network_fallback=True,
                                   no_gui_fallback=True)

    @property
    def auto_update(self):
        return False if not self.neon_core else \
            self.settings.get('auto_update')

    @property
    def allow_update(self):
        return False if not self.neon_core else \
            self.settings.get('allow_update')

    # TODO: Move to __init__ after stable ovos-workshop
    def initialize(self):
        self.make_active()  # Make this skill active so that it never
        # create_daemon(self.server_bus.run_forever())

        self.runtime_execution = {
            "variable": self._run_variable,
            "execute": self._run_execute,
            "loop": self._run_loop,
            "python": self._run_python,
            "speak": self._run_neon_speak,
            "neon speak": self._run_neon_speak,
            "name speak": self._run_name_speak,
            "case": self._run_case,
            "exit": self._run_exit,
            "if": self._run_if,
            "else": self._run_else,
            "goto": self._run_goto,
            "sub_values": self._run_sub_values,
            "sub_key": self._run_sub_string,
            "set": self._run_set,
            "reconvey": self._run_reconvey,
            "name reconvey": self._run_reconvey,
            "email": self._run_email,
            "language": self._run_language,
            "run": self._run_new_script
        }

        self.variable_functions = {
            "select_one": self._variable_select_one,
            "voice_input": self._variable_voice_input,
            "table_scrape": self._variable_table_scrape_to_dict,
            "random": self._variable_random_select,
            "closest": self._variable_closest,
            "profile": self._variable_profile,
            "skill": self._variable_skill
        }

        # # Catch invalid/uninitialized update key
        # if not self.settings.get("updates"):
        #     self.ngi_settings.update_yaml_file("updates", value={}, final=True)

        # Remove all listeners and clear signals before re-registering
        try:
            # self.remove_event("cc_loop:utterance")
            # self.remove_event('recognizer_loop:audio_output_end')
            self.remove_event('speak')
            # self.clear_signals("CC")
        except Exception as e:
            LOG.error(e)

        # Add event listeners
        self.add_event("neon.script_upload", self._handle_script_upload)
        self.add_event("neon.script_exists", self._script_exists)
        self.add_event("neon.run_alert_script", self.handle_start_script)
        self.add_event("neon.friendly_chat", self._run_friendly_chat)
        self.add_event('speak', self.check_speak_event)
        LOG.debug(">>> CC Skill Initialized! <<<")

        if self.auto_update:
            self._update_scripts()

    @intent_handler(IntentBuilder("UpdateScripts").require("UpdateScripts").optionally("Neon").build())
    def handle_update_scripts(self, message):
        if self.allow_update:
            LOG.debug(message)
            self.speak_dialog("update_started")
            success = self._update_scripts()
            time.sleep(1)
            if success:
                self.speak_dialog("update_success", message=message)
            else:
                self.speak_dialog("update_failed", message=message)
        else:
            self.speak_dialog("update_disallowed")

    @intent_handler(IntentBuilder("TellAvailableScripts").require('tell').build())
    def handle_tell_available(self, message):
        available = [os.path.splitext(x)[0].replace("_", " ") for x in os.listdir(self.text_location)
                     if os.path.isfile(os.path.join(self.text_location, x)) and x.endswith(".ncs")]
        LOG.info(available)
        if available:
            self.speak_dialog("available_script", {"available": f'{", ".join(available[:-1])}, and {available[-1]}'})
            if request_from_mobile(message):
                pass
                # TODO: Implement mobile handler
                # self.mobile_skill_intent("scripts_list", {"files": available}, message)
                # self.socket_io_emit("scripts_list", f"&files={available}", message.context["flac_filename"])

    @intent_handler(IntentBuilder("SetDefault").require('default'))
    def handle_set_default(self, message):
        utt = message.data.get("utterance")
        script_name = " ".join(utt.split("to")[1:]).strip().replace(" ", "_")
        LOG.info(script_name)
        available = [os.path.splitext(x)[0] for x in os.listdir(self.text_location)
                     if os.path.isfile(os.path.join(self.text_location, x))]
        if script_name in available:
            LOG.debug("Good Request")
            if request_from_mobile(message):
                # self.speak(f"Updating your startup script to {script_name}")
                self.speak_dialog("startup_script", {"script_name": script_name}, private=True)
                # TODO: Implement mobile handler
                # self.mobile_skill_intent("scripts_default", {"name": script_name}, message)
                # self.socket_io_emit("scripts_default", f"&name={script_name}", message.context["flac_filename"])
            # TODO: Non-Mobile startup script DM
        else:
            self.speak_dialog("NotFound", {"file_to_open": script_name.replace('_', ' ')})

    # TODO: consider how to handle this with compiled scripts
    @intent_handler(IntentBuilder("EmailScript").optionally('Neon').require('email').require('script'))
    def handle_email_file(self, message):
        if request_for_neon(message):
            utt = message.data.get("utterance")
            script_name = " ".join(utt.split("my")[1:]) \
                .strip().replace(" ", "_").replace(message.data.get("script"), "").rstrip("_")
            # LOG.info(script_name)
            available = [os.path.splitext(x)[0] for x in os.listdir(self.text_location)
                         if os.path.isfile(os.path.join(self.text_location, x))]
            LOG.info(available)
            if script_name in available:
                file_to_send = os.path.join(self.text_location, f"{script_name}.txt")
                LOG.debug(f"Good Request: {file_to_send}")

                # Get user email address
                preference_user = get_user_prefs(message)["user"]
                email_addr = preference_user["email"]

                if email_addr:
                    with open(file_to_send, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode("utf-8")
                    attachments = {f"{script_name}.txt": encoded}
                    # LOG.debug(f"file copied to {dest}")
                    title = f"Neon Script: {script_name.replace('_', ' ')}"
                    body = f"\nAttached is your requested Neon Script: {script_name}\n\n-Neon"
                    self.send_email(title, body, email_addr=email_addr, attachments=attachments)
                    self.speak_dialog("email_sent", {"script": script_name, "email": email_addr})
                else:
                    self.speak_dialog("no_email")
            else:
                self.speak_dialog("NotFound", {"file_to_open": script_name.replace('_', ' ')})

    @intent_handler(IntentBuilder("StartCustom").require("file_to_run").build())
    def handle_start_script(self, message):
        """
        Loads a script as active for the calling user
        :param message: Message object
        :return:
        """
        user = get_message_user(message)
        LOG.debug(message.data.get("utterance"))
        file_to_run = message.data.get('file_to_run')
        script_filename = file_to_run.rstrip().replace(" ", "_").replace("-", "_")
        LOG.info(script_filename)
        # active_dict = self.active_conversations.get(user).get_current_conversation()
        # LOG.info(f"Active dict is {active_dict}")
        LOG.debug(user)
        # Start transcript file
        os.makedirs(self.transcript_location, exist_ok=True)

        # Check if compiled or text script exists
        if not self._script_file_exists(script_filename):
            self.speak_dialog("NotFound", {"file_to_open": script_filename.replace('_', ' ')})
            # self.active_conversations.pop(user)
        elif self._check_script_file(script_filename + self.file_ext):
            # # Check if the file has already been parsed and cached or if we need to parse it here
            # if not self._check_script_file(active_dict["script_filename"] + self.file_ext):
            #     LOG.info(f'{active_dict["formatted_script"]} not yet parsed!')
            #     try:
            #         # Try to parse if we have the script parser available
            #         from script_parser import ScriptParser
            #         output = ScriptParser().parse_script_to_file(os.path.join(self.__location__, "script_txt",
            #                                                                   active_dict["script_filename"] + ".nct"))
            #         # Update our active_dict in case internal title doesn't match filename
            #         output_name = os.path.splitext(os.path.basename(output))[0]
            #         LOG.info(f"Parsed to {output_name}")
            #         active_dict["script_filename"] = output_name
            #     except Exception as e:
            #         LOG.error(e)
            # We have this in cache now, load values from there
            LOG.debug("Loading from Cache!")
            try:
                cache = self.get_cached_data(script_filename + self.file_ext,
                                             os.path.join(self.__location__, "script_txt"))
                # TODO: Claps and Synonyms here! DM
                LOG.info(json.dumps(cache, indent=4))
            except Exception as e:
                LOG.error(e)
                # active_dict = self._load_to_cache(active_dict, file_to_run, user)
                cache = None
            # if not cache or cache == {}:
            #     LOG.warning(f'{active_dict["script_filename"]} empty in cache!')
            #     # self._load_to_cache(active_dict, file_to_run, user)
            #     # cache = self.get_cached_data(f'scripts/{active_dict["script_filename"]}')
            #     # LOG.info(json.dumps(cache, indent=4))
            #     # LOG.info(f'Checking for cache AP')

            LOG.info(f'{script_filename} loaded from cache')
            try:
                script_meta = cache[9]
            except Exception as e:
                LOG.error(e)
                script_meta = None
            # initialize conversation
            self._init_conversation(user=user, script_meta=script_meta, script_filename=script_filename)
            active_dict = self.active_conversations.get(user).get_current_conversation()

            self.update_transcript(f'RUNNING SCRIPT {active_dict["script_filename"]}\n',
                                   filename=active_dict["script_filename"],
                                   start_time=active_dict["script_start_time"]
                                   )
            try:
                active_dict["formatted_script"] = cache[0]
                active_dict["speaker_data"] = cache[1]
                active_dict["variables"] = cache[2]
                active_dict["loops_dict"] = cache[3]
                active_dict["goto_tags"] = cache[4]
                active_dict["timeout"] = cache[5]
                active_dict["timeout_action"] = cache[6]
                # active_dict["script_meta"] = cache[9]
            except Exception as e:
                LOG.error(e)
                active_dict.reset_values()
                # TODO: Speak error! DM
                # active_dict = self.active_conversations[user]
                # active_dict = self._load_to_cache(active_dict, file_to_run, user)

            # Check if script was found and loaded
            if active_dict:
                LOG.debug(f">>> {json.dumps(active_dict.to_json(), indent=4)}")
                # If language is specified, change to that now
                # if active_dict["speaker_data"]:
                #     cache_lang = None
                #     for lang, code in self.configuration_available["ttsOpts"].items():
                #         if str(code).lower() == str(self.user_info_available["speech"]["tts_language"]).lower():
                #             cache_lang = lang
                #             LOG.info(f"Caching start language: {cache_lang}")
                #             break
                #     if cache_lang:
                #         LOG.info(f'Caching start language of {cache_lang}')
                #         active_dict["user_language"] = f'{cache_lang} ' \
                #                                        f'{self.user_info_available["speech"]["tts_gender"]}'
                #     self._update_language(message, active_dict["speaker_data"])
                # self.create_signal(f"{user}_CC_active")
                # self.speak_init_message(message)
                # active_dict["outer_option"] = 0
                active_dict["last_indent"] = 0
                # active_dict["current_index"] = 1

                # Check if a starting tag was specified at skill run

                spoken = message.data.get("utterance")

                start_index = None
                try:
                    to_parse = spoken.split(file_to_run)[1]
                    LOG.debug(to_parse)
                    if " at " in to_parse:
                        start_tag = to_parse.split(" at ", 1)[1].replace(" ", "_")
                        LOG.debug(start_tag)
                        LOG.debug(f'searching {dict(active_dict["goto_tags"]).keys()}')
                        for key in dict(active_dict["goto_tags"]).keys():
                            if key in start_tag:
                                LOG.debug(f"DM: found {key} in goto_tags")
                                start_index = active_dict["goto_tags"][key]
                                break
                        LOG.debug(f"DM: starting at {start_index}")
                except IndexError:
                    LOG.debug("Cannot split utterance by the file name")

                # If a starting tag was specified, go to the associated index
                if start_index:
                    active_dict["current_index"] = start_index
                else:
                    # Read through file until we get to something to actually execute
                    while active_dict["current_index"] <= len(active_dict["formatted_script"]):
                        LOG.debug(active_dict["formatted_script"][active_dict["current_index"]]["command"])
                        if active_dict["formatted_script"][active_dict["current_index"]]["command"]\
                                not in self.header_options:
                            break
                        active_dict["current_index"] += 1
                LOG.debug(f'script starting at {active_dict["current_index"]}')
                # LOG.debug(f"DM: Continue Script Execution Call")
                self._continue_script_execution(message, user)
        else:
            self.speak_dialog("ProblemInFile", {"file_name": script_filename.replace('_', ' ')})
            self.active_conversations.pop(user)

    def _run_friendly_chat(self, message: Message):
        """
        A wrapper around handle_start_script used to run the friendly_chat script specifically for the symptom-checker.
        It emits a response that the request has been processed back to the checker.
        :param message: a message from the symptom-checker
        :return:
        """
        try:
            self.handle_start_script(message)
        except Exception as e:
            LOG.error(e)
            self.bus.emit(message.reply("neon.friendly_chat.response",
                                        context={"friendly_chat_executed": False}))
        else:
            self.bus.emit(message.reply("neon.friendly_chat.response",
                                        context={"friendly_chat_executed": True}))

    def _script_exists(self, message):
        LOG.info(message)
        script_name = self._get_script_name(message)
        status = self._script_file_exists(script_name)
        self.bus.emit(message.reply("neon.script_exists.response", data={"script_name": script_name, "script_exists": status}))

    def _get_script_name(self, message: Message) -> str:
        """
        Tries to locate a filename in the input utterance and returns that filename or None

        This one will be depreciated once we place all the scripts in a single dir that is available
        to all skills, e.g. ~/.neon

        :param message: Message associated with request
        :return: Requested script name (may be None)
        """
        # consider having several script file names starting with the same words, e.g. "pat", "pat test"
        candidates = []
        utt = message.data.get("utterance")
        file_path_to_check = os.path.join(self.__location__, "script_txt")
        LOG.debug(file_path_to_check)
        # Look for recording by name if recordings are available
        for f in os.listdir(file_path_to_check):
            filename = os.path.splitext(f)[0]
            LOG.info(f"Looking for {filename} in {utt}")
            if filename in utt:
                candidates.append(filename)
        try:
            script_name = max(candidates, key=len)
        except ValueError:
            script_name = None
        return script_name

    def _script_file_exists(self, script_name):
        """
        Checks if the requested script exits
        :param script_name: script basename (script name with " " replaced with "_")
        :return: Boolean file exists
        """
        file_path_to_check = self.__location__ + "/script_txt/" + script_name + self.file_ext
        LOG.info(file_path_to_check)
        if not os.path.isfile(file_path_to_check):
            second_path_to_check = self.__location__ + "/script_txt/" + script_name + ".nct"
            return os.path.isfile(second_path_to_check)
        return True

    def _init_conversation(self, user, script_meta=None, script_filename=None):
        """
        Initialize a conversation manager for user if does not exist and add a new conversation there
        :param user: nick on klat server, else "local"
        :param script_meta: script metadata from cache
        :param script_filename: script filename to run
        :return:
        """
        # initialize a conversation manager for user if does not exist already
        if user not in self.active_conversations.keys():
            self.active_conversations[user] = ConversationManager(user)

        # push a new conversation to the conversation manager
        current_conversation = Conversation(script_meta=script_meta, script_filename=script_filename)
        self.active_conversations.get(user).push(current_conversation)

    def _update_scripts(self):
        """
        Updates conversation files from Git
        """
        try:
            git_remote = self.settings["scripts_repo"]
            branch = self.settings["scripts_branch"]

            # Initialize Scripts repository
            try:
                if not os.path.isdir(self.text_location):
                    os.makedirs(self.text_location)
                repo = git.Repo(self.text_location)
            except InvalidGitRepositoryError:
                shutil.move(self.text_location, f"{self.text_location}_bak")
                repo = git.Repo.clone_from("https://github.com/neongeckocom/neon-scripts", self.text_location)

            urls = repo.remote("origin").urls
            for url in urls:
                # Check for configuration repo change
                if url != git_remote:
                    # TODO: Backup? DM
                    LOG.debug("Update remote!")
                    repo.delete_remote("origin")
                    repo.create_remote("origin", git_remote)
                    repo.git.reset("--hard")
                    repo.remote("origin").pull(branch)
                    repo.git.reset("--hard", f"origin/{branch}")
            repo.remote("origin").pull(branch)

            # Handle non-git scripts backup
            if os.path.isdir(f"{self.text_location}_bak"):
                shutil.move(f"{self.text_location}_bak", os.path.join(self.text_location, "backup", "old"))
            self.update_skill_settings({"last_updated": str(datetime.datetime.now())}, skill_global=True)
            # self.ngi_settings.update_yaml_file("last_updated", value=str(datetime.datetime.now()), final=True)
            return True
        except Exception as e:
            LOG.error(e)
            return False

    def _check_script_file(self, filename, compiled=True):
        """
        Checks if the passed script file is valid and returns True or False
        :param filename: filename to check
        :return:
        """
        if compiled:
            try:
                cache_data = self.get_cached_data(filename, os.path.join(self.__location__, "script_txt"))
                # meta = {"cversion": self._version,
                #         "compiled": round(time.time()),
                #         "compiler": "Neon AI Script Parser",
                #         "title": None,
                #         "author": None,
                #         "description": "",
                #         "raw_file": "".join(raw_text)}
                if cache_data[9].get("cversion"):
                    LOG.debug(f'compiler version={cache_data[9].get("cversion")}')
                    return True
                else:
                    return False
            except Exception as e:
                LOG.error(e)
                return False
        else:
            # DEPRECIATED METHOD
            with open(os.path.join(self.__location__, 'script_txt', filename)) as file:
                for line in file:
                    if str(line).startswith("Script: "):
                        return True
                    elif str(line).strip().startswith('#'):
                        pass
                    elif str(line).strip():
                        return False
            # Empty file
            return False

    def _continue_script_execution(self, message, user="local"):
        """
        Continues iterating through script execution until we have to wait for a response
        :param user: nick on klat server, else "local"
        """
        LOG.info(f"THE MESSAGE CONTEXT IS {message.context}")
        line_to_evaluate, active_dict = None, None
        try:
            active_dict = self.active_conversations.get(user).get_current_conversation()
            # Catch when we are waiting for input
            if user not in self.awaiting_input and active_dict:
                LOG.debug(f'Continuing {active_dict["script_filename"]} script from index {active_dict["current_index"]}')

                # Continue only if there is an active script for the user
                if active_dict["formatted_script"]:
                    # Read values out of dictionary (current_index is line index, not line number)
                    LOG.debug(f'Going to idx: {active_dict["current_index"]} in script of length: '
                              f'{len(active_dict["formatted_script"])}')
                    if active_dict["current_index"] >= len(active_dict["formatted_script"]):
                        LOG.error("Requested line outside of script length! Exiting.")
                        self.speak_dialog("error_at_line", {"error": "end of file",
                                                            "line": active_dict["current_index"],
                                                            "detail": "",
                                                            "script": active_dict["script_filename"]})
                        self._run_exit(user, "", message)
                    else:
                        line_to_evaluate = active_dict["formatted_script"][active_dict["current_index"]]
                        LOG.debug(f'Line: {line_to_evaluate}')
                        prev_line_indent = active_dict["last_indent"]
                        active_dict["last_indent"] = \
                            active_dict["formatted_script"][active_dict["current_index"]]["indent"]
                        LOG.debug(f'previous line was indented {prev_line_indent}. '
                                  f'current line at {line_to_evaluate["indent"]}')
                        command = line_to_evaluate["command"]
                        text = line_to_evaluate["text"]
                        execute_this_line = True

                        # Check if outdented
                        if line_to_evaluate["indent"] < prev_line_indent:
                            parent_case_indents = list(deepcopy(line_to_evaluate["parent_case_indents"]))
                            execute_this_line = True

                            # Iterate over parent cases
                            while parent_case_indents:
                                LOG.debug(f'parent case in effect! {parent_case_indents}')
                                parent_indent = parent_case_indents.pop()

                                # This is the another case
                                if line_to_evaluate["indent"] == parent_indent + 1:
                                    # line_to_evaluate["parent_case_indents"].pop()
                                    LOG.debug(f"case ended")
                                    execute_this_line = False
                                    # Iterate through formatted_script until indent
                                    # less than or equal to indent_of_parent
                                    while active_dict["formatted_script"][active_dict["current_index"]]["indent"] > \
                                            parent_indent:
                                        if active_dict["current_index"] == len(active_dict["formatted_script"]) - 1:
                                            LOG.warning("EOF reached evaluating case!")
                                            self._run_exit(user, text, message)
                                            break
                                        active_dict["current_index"] += 1
                                    # LOG.debug(f"DM: Continue Script Execution Call")
                                    self._continue_script_execution(message, user)
                                    break
                                # We are still in our case, continue as normal
                                elif line_to_evaluate["indent"] > parent_indent + 1:
                                    break

                                # Else we are outside this case, look for an outer one and continue
                                else:
                                    LOG.debug(f'Outside of case, parent_case_indents={parent_case_indents}')

                        # This is outside any cases
                        if execute_this_line:
                            LOG.debug(f'execute {command}: {text}')
                            # This is an executable line
                            if command in self.runtime_execution:
                                # LOG.info(f"{command} IN RUNTIME EXECUTION")
                                # If this is not a sub_key/value command
                                if command not in self.substitute_wildcards:
                                    # LOG.info(f"{command} NOT IN SUBSTITUTE WILDCARDS")
                                    # Make sure string comparators are capitalized and right value is a set
                                    if command == "if":
                                        left, right, comparison = None, None, ""
                                        for comparator in self.string_comparators:
                                            if comparator.lower() in text.lower().split():
                                                comparison = comparator
                                                text = re.sub(f" {comparator.lower()} ", f" {comparator} ", text)
                                                left, right = text.split(f" {comparator} ", 1)
                                                break  # Only one comparator should be in a line
                                            elif f"!{comparator.lower()}" in text.lower().split():
                                                comparison = f"!{comparator}"
                                                text = re.sub(f" !{comparator.lower()} ", f" !{comparator} ", text)
                                                left, right = text.split(f" !{comparator} ", 1)
                                                break  # Only one comparator should be in a line

                                        # Make sure right value is a list for IN/!IN
                                        if left and right and "[" not in right:
                                            LOG.debug(f"updating right={right}")
                                            right = re.sub("}", "[*]}", right)
                                            LOG.debug(f"updating right={right}")
                                            text = f" {comparison} ".join([left, right])
                                        LOG.debug(text)
                                    # else:
                                    parsed_text = self._substitute_variables(user, text, message, False)
                                    LOG.info(f"SUCCESSFULLY PARSED {text} to {parsed_text}")
                                else:
                                    parsed_text = text
                                # parsed_text = normalize(parsed_text)  WYSIWYG, no normalization necessary
                                LOG.debug(f"runtime_execute({command}|{parsed_text})")
                                LOG.debug(line_to_evaluate)
                                message.data["parser_data"] = deepcopy(line_to_evaluate.get("data"))
                                LOG.debug(f'parser_data={message.data.get("parser_data")}')

                                # # TODO: Annotate this DM
                                try:
                                    if message.data.get("parser_data"):
                                        LOG.info(f'PARSER DATA {message.data.get("parser_data")} and '
                                                 f'PARSED TEXT {parsed_text}')
                                        for key, val in message.data.get("parser_data").items():
                                            if val and isinstance(val, str) and "{" in val and "}" in val and \
                                                    command != "variable":
                                                LOG.info(f"variables in: {val}")
                                                message.data.get("parser_data")[key] = \
                                                    self._substitute_variables(user, val, message, False)
                                except Exception as e:
                                    LOG.error(f"ERROR IN INNER TRY{e}")

                                # Execute the line
                                LOG.debug(f"Active script before execution is {active_dict['script_filename']}")
                                self.runtime_execution[command](user, parsed_text, message)
                                LOG.debug(f"Active script after execution is {active_dict['script_filename']}")
                                if user in self.active_conversations:
                                    self._continue_script_execution(message, user)

                            # This is a variable assignment line TODO: Can we ever reach this? DM
                            elif command in self.variable_functions:
                                LOG.info(f'PARSE OUT VARIABLE FOR {text}')
                                # Parse out variable in line
                                if '{' in text and '}' in text:
                                    LOG.warning(f"Use of braces in variable functions is depreciated, use parentheses"
                                                f" | {text}")
                                    key = str(text).split('{')[1].split('}')[0]
                                elif '(' in text and ')' in text:
                                    key = str(text).split('(')[1].split(')')[0]
                                else:
                                    LOG.warning(f"variable function: {command} called without an argument")
                                    self.speak_dialog("error_at_line", {"error": "variable",
                                                                        "line": line_to_evaluate["line_number"],
                                                                        "detail": line_to_evaluate["text"],
                                                                        "script": active_dict["script_filename"].
                                                      replace('_', ' ')})
                                    return
                                # If variable doesn't exist, initialize it
                                if key.split(",")[0] not in active_dict["variables"]:
                                    LOG.info(f"INITIALIZE VAR FOR {key} IF DOES NOT EXIST")
                                    LOG.warning(f"Requested input var: {key.split(',')[0]} not yet decared!")
                                    active_dict["variables"][key.split(",")[0]] = []
                                # if isinstance(active_dict["variables"][key], str) or \
                                #         len(active_dict["variables"][key]) <= 1:
                                #     active_dict["variables"][key] = []
                                LOG.info(f"About to execute {command} for {user} with {key}")
                                self.variable_functions[command](key, user, message)
                                active_dict["current_index"] += 1
                            # This is a non-executable line, skip over to the next line
                            elif command in ('@', 'tag'):
                                LOG.debug(f"continuing past {command}")
                                active_dict["current_index"] += 1
                                # LOG.debug(f"DM: Continue Script Execution Call")
                                self._continue_script_execution(message, user)
                            # This line cannot be evaluated at this time, just move on
                            else:
                                LOG.debug(f"{command} is not a valid runtime option, nothing to execute, continuing")
                                active_dict["current_index"] += 1
                                # LOG.debug(f"DM: Continue Script Execution Call")
                                self._continue_script_execution(message, user)
        except Exception as e:
            LOG.error(e)
            LOG.error(line_to_evaluate)
            try:
                line = line_to_evaluate.get("line_number")
                script = active_dict.get("script_filename")
                detail = line_to_evaluate.get("text")
            except Exception as x:
                LOG.error(x)
                line = "unknown"
                script = "unknown"
                detail = None
            self.speak_dialog("error_at_line", {"error": "unknown",
                                                "line": line,
                                                "script": script,
                                                "detail": detail})
            self._run_exit(user, None, message)

    # Handle line commands at runtime
    def _run_execute(self, user, text, message):
        """
        Called at script execution when an execute line is encountered. Emits a message and sets "last_request" variable
        to check for the response in check_neon_speak before continuing
        :param user: nick on klat server, else "local"
        :param text: string to execute
        :param message: incoming messagebus Message
        """
        active_dict = self.active_conversations.get(user).get_current_conversation()
        parsed_data = message.data.get("parser_data")
        if parsed_data:
            text = parsed_data.get("command")
        LOG.info(f"EXECUTE {text}")
        if text == "Execute:":
            active_dict["current_index"] += 1
            # LOG.debug(f"DM: Continue Script Execution Call")
            # self._continue_script_execution(message, user)
        else:
            text = text.strip('"')
            # signal = build_signal_name(user, text)
            # LOG.info(f"SIGNAL IS {signal}")
            to_emit = build_message("execute", text, message, active_dict["speaker_data"])
            LOG.info(f"TO EMIT is {to_emit}")
            # self.create_signal(signal)
            active_dict["last_request"] = text
            self.bus.emit(to_emit)
            # LOG.info(f"{to_emit} should have been emitted")
            active_dict["current_index"] += 1
            timeout = time.time() + self.response_timeout
            # TODO: This should be an event, not looped sleep DM
            while time.time() < timeout and active_dict["last_request"] == text:
                # LOG.info("WAITING IN _RUN_EXECUTE")
                time.sleep(0.2)
            LOG.info(f"ACTIVE CONVERSATION IN EXECUTE {active_dict}")
            if active_dict["last_request"] == text:
                LOG.warning("No skill response! Timeout, continue...")
                # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_loop(self, user, text, message):
        """
        Called at script execution when a loop line is encountered
        :param user: nick on klat server, else "local"
        :param text: line containing loop name and condition (START/END/UNTIL)
        :param message: incoming messagebus Message
        """
        active_dict = self.active_conversations.get(user).get_current_conversation()
        parsed_data = message.data.get("parser_data")
        if parsed_data:
            # TODO: Add parsing and handle it here DM
            pass

        LOG.debug(f"run_loop({text})")
        if ("END" in text) or ("UNTIL" in text):
            # This is the end of a loop, continue or go to start line
            loop_name = str(text).split(" ")[1]
            goto_line = active_dict["loops_dict"][loop_name]["start"]
            repeat_loop = True

            # Check for conditional to end loop
            var_to_check = str(active_dict["loops_dict"][loop_name].get("end_variable", None)). \
                replace('{', '').replace('}', '')
            val_to_end = str(active_dict["loops_dict"][loop_name].get("end_value", None)). \
                replace('"', '').replace("'", "")

            # If we have a loop conditional
            if active_dict["variables"].get(var_to_check, None) and val_to_end:
                val_to_check = active_dict["variables"][var_to_check][0]
                LOG.debug(f"End loop if {val_to_check} ?= {val_to_end}")
                # Don't repeat if we match the end condition
                if val_to_check == val_to_end:
                    repeat_loop = False
            else:
                repeat_loop = True

            # Find the line to start at if looping
            if repeat_loop:
                LOG.debug(f"Loop repeat, find line_number {goto_line}")
                i = 0
                # Find the line the loop started at
                for line in active_dict["formatted_script"]:
                    if line["line_number"] == goto_line:
                        LOG.debug(f"goto_line: {goto_line} found at index: {i}")
                        active_dict["current_index"] = i
                        break
                    i += 1
                active_dict["current_index"] = i
            # Loop condition met, continue
            else:
                active_dict["current_index"] += 1
        else:
            # This is the start of a loop. Just continue
            active_dict["current_index"] += 1

    def _run_goto(self, user, text, message):
        """
        Called at script execution when a goto line is encountered. Goes to the specified line by number or label
        :param user: nick on klat server, else "local"
        :param text: argument to goto line; either a number or raw tag name
        :param message: incoming messagebus Message
        """
        LOG.debug(text)
        active_dict = self.active_conversations[user].get_current_conversation()

        parser_data = message.data.get("parser_data")
        if parser_data and parser_data.get("destination"):
            to_find = active_dict["goto_tags"].get(parser_data["destination"], parser_data["destination"])
        elif str(text).isnumeric():
            LOG.warning(f"No parsed destination! {text} is a number")
            to_find = int(text)
        else:
            LOG.warning(f"No parsed destination! {text} is a tag")
            if text in active_dict["goto_tags"]:
                to_find = int(active_dict["goto_tags"][text])
            else:
                LOG.warning(f"{text} is not a valid tag!")
                to_find = None

        # Iterate through formatted_script to find the correct line
        if to_find:
            LOG.debug(f"Go To line: {to_find}")
            i = 0
            for line in active_dict["formatted_script"]:
                if int(line["line_number"]) == to_find:
                    LOG.debug(f"Going to index {i}: {line}")
                    active_dict["current_index"] = i
                    active_dict["last_indent"] = line["indent"]
                    # Act as if we encountered this line at it's indent level to skip if/case checking issues
                    break
                i += 1
        else:
            error_line = active_dict["formatted_script"][active_dict["current_index"]]
            self.speak_dialog("error_at_line", {"error": "missing tag",
                                                "line": error_line["line_number"],
                                                "script": active_dict["script_filename"],
                                                "detail": error_line["text"]})
            active_dict["current_index"] += 1
        LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_python(self, user, text, message):
        """
        Called at script execution when a python line is encountered
        :param user: nick on klat server, else "local"
        :param text: string to execute
        :param message: incoming messagebus Message
        """
        active_dict = self.active_conversations[user].get_current_conversation()
        # TODO: Use parser_data
        if text == "Python:":
            active_dict["current_index"] += 1
            # LOG.debug(f"DM: Continue Script Execution Call")
            # self._continue_script_execution(message, user)
        else:
            from math import sqrt, log, log10, sin, cos, tan, sinh, cosh, tanh, asin, acos, atan, e, pi
            LOG.debug(text)
            if "=" in text:
                var_to_assign = text.split('=', 1)[0].strip()
                to_evaluate = text.split('=', 1)[1].strip()
            else:
                var_to_assign = None
                to_evaluate = text
            try:
                LOG.debug(to_evaluate)
                ret = eval(to_evaluate, {}, {"sqrt": sqrt, "ln": log, "log": log10,
                                             "sin": sin, "cos": cos, "tan": tan,
                                             "sinh": sinh, "cosh": cosh, "tanh": tanh,
                                             "asin": asin, "acos": acos, "atan": atan,
                                             "sleep": time.sleep, "time": time, "e": e, "pi": pi})
                LOG.debug(ret)
                if var_to_assign:
                    if isinstance(ret, int):
                        ret = int(ret)
                    else:
                        ret = round(ret, 3)
                    LOG.debug(ret)
                    active_dict["variables"][var_to_assign] = str(ret)
            except Exception as e:
                LOG.error(e)
                self.speak_dialog("error_at_line", {"error": "python execution",
                                                    "line": active_dict["current_index"],
                                                    "script": re.sub("_", " ", active_dict["script_filename"]),
                                                    "detail": text})
            active_dict["current_index"] += 1

    def _run_neon_speak(self, user, text, message):
        """
        Called at script execution when a Neon speak line is encountered
        :param user: nick on klat server, else "local"
        :param text: string to speak
        :param message: incoming messagebus Message
        """
        active_dict = self.active_conversations[user].get_current_conversation()
        parser_data = message.data.get("parser_data")
        if parser_data:
            if parser_data.get("name") != "Neon":          # TODO: Neon/Name speak should be the same now!
                LOG.warning(f"Neon Speak called instead of Name Speak!!")
                self._run_name_speak(user, text, message)
                return
            text = clean_quotes(parser_data.get("phrase"))
        else:
            text = clean_quotes(text)

        if not text or text.lower().endswith("speak:"):
            active_dict["current_index"] += 1
        else:
            active_dict["current_index"] += 1  # Increment position first in case speak is fast

            to_speak = build_message("neon speak", text, message, active_dict["speaker_data"])
            active_dict["last_request"] = text
            LOG.info(f"ABOUT TO SPEAK {text}")
            self.speak(text, message=to_speak)
            # LOG.info(f"{text} SUCCESSFULLY SPOKEN")
            user_input = message.data.get("utterances")
            if user_input:
                LOG.debug(f'{message.data.get("parser_data").keys()} AP')
                self.update_transcript(
                    f'{datetime.datetime.now().isoformat()}, {user} said: \"{user_input[0]}\" \n',
                    filename=active_dict["script_filename"],
                    start_time=active_dict["script_start_time"]
                    )
            self.update_transcript(f'{datetime.datetime.now().isoformat()}, Neon said: "{text}" \n',
                                   filename=active_dict["script_filename"],
                                   start_time=active_dict["script_start_time"]
                                   )
        # self._continue_script_execution(message, user)

    def _run_name_speak(self, user, text, message):
        # TODO: Neon/Name speak are the same now!
        """
        Called at script execution when a named speak line is encountered
        :param user: nick on klat server, else "local"
        :param text: string to speak
        :param message: incoming messagebus Message
        """
        active_dict = self.active_conversations.get(user).get_current_conversation()
        # Catch indented section start line
        if text == "Name speak:":
            active_dict["current_index"] += 1
        else:
            speaker_dict = active_dict["speaker_data"]
            if message.data.get("parser_data"):
                parser_data = message.data.get("parser_data")
                speaker = clean_quotes(parser_data.get("name"))  # TODO: Handle variable here DM
                text = parser_data.get("phrase", text)
                if '"' in text or "'" in text:
                    text = clean_quotes(text)
                speaker_data = deepcopy(speaker_dict)
                speaker_data["name"] = speaker
                speaker_data["gender"] = parser_data.get("gender", speaker_dict.get("gender"))
                speaker_data["language"] = parser_data.get("language", speaker_dict.get("language"))
                LOG.debug(speaker_data)
            else:
                LOG.warning("Couldn't parse speaker data!")
                speaker, text = text.split(':', 1)
                # Catch when multiple parameters are passed
                if ',' in speaker:
                    parts = speaker.split(',')
                    LOG.debug(parts)
                    gender = speaker_dict.get("gender")
                    language = speaker_dict.get("language")
                    name = speaker
                    for part in parts:
                        part = part.strip()
                        LOG.debug(part)
                        if part in ("male", "female"):
                            gender = part
                        elif len(part) == 5 and part[2] == '-':
                            language = part
                        else:
                            name = part

                    # Handle passed gender change without specified language
                    if not language:
                        language = get_user_prefs(message)["speech"]["tts_language"]

                    LOG.debug(f"{gender} {language} {name} {speaker}")

                    speaker_data = {"name": name, "gender": gender, "language": language, "override_user": True}
                else:
                    speaker_data = speaker_dict

            LOG.debug(f"{speaker} Speak: {text}")
            text = str(text).strip().strip('"')
            to_speak = build_message("neon speak", text, message, speaker=speaker_data)
            LOG.debug(speaker)
            LOG.debug(to_speak.data)
            active_dict["last_request"] = text
            self.speak(text, message=to_speak)
            user_input = message.data.get("utterances")
            if user_input:
                self.update_transcript(f'{datetime.datetime.now().isoformat()}, {user} said: \"{user_input[0]}\" \n',
                                       filename=active_dict["script_filename"],
                                       start_time=active_dict["script_start_time"]
                                       )
            self.update_transcript(f'{datetime.datetime.now().isoformat()}, {speaker} said: "{text}" \n',
                                   filename=active_dict["script_filename"],
                                   start_time=active_dict["script_start_time"]
                                   )
            active_dict["current_index"] += 1
        # self._continue_script_execution(message, user)

    def _run_case(self, user, text, message):
        """
        Called at script execution when a case statement is encountered
        :param user: nick on klat server, else "local"
        :param text: case statement with variable condition
        :param message: incoming messagebus Message
        """

        LOG.debug(f"DM: run_case({text})")
        active_dict = self.active_conversations[user].get_current_conversation()
        parser_data = message.data.get("parser_data")
        if parser_data:
            val_to_check = parser_data.get("variable")
        else:
            try:
                if ' ' in text:
                    val_to_check = str(text).split(' ')[1].replace(':', '').strip()
                else:
                    val_to_check = str(text).strip()
            except Exception as e:
                LOG.error(e)
                active_dict["current_index"] -= 1
                val_to_check = None
                self._run_exit(user, text, message)

        # LOG.debug(f"DM: checking case with value of {val_to_check}")
        indent_of_case = active_dict["formatted_script"][active_dict["current_index"]]["indent"]
        # LOG.debug(f"DM: case indent={indent_of_case}")
        line_index_to_check = active_dict["current_index"] + 1
        LOG.debug(f'val: {val_to_check}, indent: {indent_of_case}, index: {line_index_to_check}')

        # Iterate through following script lines
        if line_index_to_check and val_to_check:
            while line_index_to_check <= len(active_dict["formatted_script"]):
                try:
                    line_to_evaluate = active_dict["formatted_script"][line_index_to_check]
                    # LOG.debug(f"{line_to_evaluate}")
                    # If the indent is less than or equal to the case statement, we didn't get a valid response
                    if line_to_evaluate["indent"] <= indent_of_case:
                        LOG.debug(f"Line outdented from case {line_to_evaluate}")
                        # Repeat variable assignment and case evaluation
                        active_dict["current_index"] -= 1
                        # LOG.debug(f"DM: Continue Script Execution Call")
                        # self._continue_script_execution(message, user)
                        break
                    # This line is inside of a case option, just check the next line
                    elif line_to_evaluate["indent"] > indent_of_case + 1:
                        line_index_to_check += 1
                    # This is a valid case option, check if we should go here
                    else:
                        case_to_check = str(line_to_evaluate["text"]).lower().rstrip('\n').strip('"')
                        # TODO: Parse above in parser DM
                        LOG.debug(f'Checking case: {case_to_check}')
                        # Parse valid options to match case
                        options = [case_to_check]
                        if " or " in case_to_check:
                            options = case_to_check.split(" or ")
                        # Check if match
                        if val_to_check in options:
                            LOG.debug(f"matched case! go to index {line_index_to_check + 1}")
                            active_dict["current_index"] = line_index_to_check + 1
                            # LOG.debug(f"DM: Continue Script Execution Call")
                            # self._continue_script_execution(message, user)
                            break
                        else:
                            LOG.debug(f"{val_to_check} not found in {options}")
                            line_index_to_check += 1
                except Exception as e:
                    LOG.error(e)
                    break
        # self._continue_script_execution(message, user)

    def _run_exit(self, user, text, message):
        """
        Called when `Exit` line is reached, user requests exit, or a fatal script error is encountered. Notifies user
        of exit, resets language if changed at script start, and clears values for next script request.
        :param user: nick on klat server, else "local"
        :param text: `Exit` line in script file
        :param message: messagebus object of last user input
        """
        LOG.debug(f"Exiting {text}")
        active_dict = self.active_conversations.get(user).get_current_conversation()

        # Overwrite speaker data so this message comes from Neon
        message.data["speaker"] = None
        # LOG.debug(message.data)
        self.speak_dialog("Exiting",
                          {"file_name": str(active_dict["script_filename"]).replace('_', ' ')})

        # Cancel timeout event
        event_name = f"CC_{user}_conversation"
        self.cancel_scheduled_event(event_name)

        # Revert language if we changed it
        # LOG.debug(f'on exit original lang is {active_dict["user_language"]}')
        # if active_dict["user_language"] and message:
        #     self._update_language(message, active_dict["user_language"])

        # Resume pending script by removing the script-to-exit from the pending script stack
        popped_conversation = self.active_conversations.get(user).pop()
        # Update the user scope of variables
        self.active_conversations[user].update_user_scope(popped_conversation)

        if len(self.active_conversations.get(user)) != 0:
            active_dict = self.active_conversations.get(user).get_current_conversation()
            active_dict['current_index'] += 1
            LOG.debug(f"After exit, active dict is {active_dict['script_filename']}")
        else:
            # Clear signals and values because there are no pending scripts left in the stack
            # LOG.info(f"CLEARING SIGNALS FOR {user}")
            # self.clear_signals(f"{user}_CC_")
            self.active_conversations.pop(user)
            if self.gui_enabled:
                self.gui.clear()

    def _run_if(self, user, text, message):
        """
        Called at script execution when an if line is encountered. Evaluate the condition and either continue at the
        next line, or at the line following the "else" at the same indent as this one
        :param user: nick on klat server, else "local"
        :param text: "else:"
        :param message: incoming messagebus Message
        """
        # active_dict = self.active_conversations[user]
        parsed = message.data.get("parser_data")
        LOG.info(f"RUN_IF TEXT {text} | PARSED {parsed}")
        if parsed:
            comparator = parsed.get("comparator")
            if comparator == "BOOL":
                variable = parsed.get("variable")  # If comparator == "BOOL"
                LOG.info(f"RUN_IF VARIABLE {variable}")
                if variable:
                    execute_if = True
                else:
                    execute_if = False
            else:
                left = parsed.get("left")
                right = parsed.get("right")
                if isinstance(left, str):
                    left = clean_quotes(left).strip()
                    if left.isnumeric():
                        left = int(left)
                if isinstance(right, str):
                    right = clean_quotes(right).strip()
                    if right.isnumeric():
                        right = int(right)

                execute_if = True
                LOG.debug(f"Checking: {left} {comparator} {right}")
                if not comparator:
                    LOG.warning(f"no valid comparator found in {text}")
                    execute_if = False
                elif comparator == "==" and left != right:
                    LOG.debug(f"not equal, go to else")
                    execute_if = False
                elif comparator == "!=" and left == right:
                    LOG.debug(f"equal, go to else")
                    execute_if = False
                elif comparator == ">" and left <= right:
                    LOG.debug(f"less than or equal, go to else")
                    execute_if = False
                elif comparator == "<" and left >= right:
                    LOG.debug(f"greater than or equal, go to else")
                    execute_if = False
                elif comparator == ">=" and left < right:
                    LOG.debug(f"less than, go to else")
                    execute_if = False
                elif comparator == "<=" and left > right:
                    LOG.debug(f"greater than, go to else")
                    execute_if = False

                # String/List comparators are handled here
                elif any(x for x in self.string_comparators if x in comparator):
                    # Catch error where right is a string
                    if isinstance(right, str) and ',' in right:
                        right = str(re.sub(", ", ",", right)).lower().split(',')
                        LOG.warning(f"right was a string! now={right}")
                    elif isinstance(right, str):
                        right = [right.lower()]
                        LOG.warning(f"right was a string! now={right}")

                    if comparator == "IN" and str(left) not in right:
                        LOG.debug(f"not in, go to else")
                        execute_if = False
                    elif comparator == "!IN" and str(left) in right:
                        LOG.debug(f"in, go to else")
                        execute_if = False
                    elif comparator.endswith("CONTAINS"):  # Handle CONTAINS/!CONTAINS
                        LOG.debug(f"left={left}")
                        LOG.debug(f"right={right}")
                        contains = False
                        # Iterate over right items to find a match
                        for opt in right:
                            if f" {opt} " in f" {left} ":  # Maybe multiple words, can't just split
                                LOG.info(f"Found {opt} in {left}")
                                contains = True
                                break
                        if contains and comparator.startswith("!") or not contains:
                            execute_if = False
                    elif comparator.endswith("STARTSWITH"):
                        LOG.debug(f"left={left}")
                        LOG.debug(f"right={right}")
                        startswith = False
                        # Iterate over right items to find a match
                        for opt in right:
                            if left.startswith(opt):
                                LOG.info(f"{left} starts with {opt}")
                                startswith = True
                                break
                        if startswith and comparator.startswith("!") or not startswith:
                            execute_if = False
                    elif comparator.endswith("ENDSWITH"):
                        LOG.debug(f"left={left}")
                        LOG.debug(f"right={right}")
                        endswith = False
                        # Iterate over right items to find a match
                        for opt in right:
                            if left.endswith(opt):
                                LOG.info(f"{left} ends with {opt}")
                                endswith = True
                                break
                        if endswith and comparator.startswith("!") or not endswith:
                            execute_if = False
                else:
                    LOG.debug(f"Statement is True")

        else:
            # TODO: DEPRECIATED DM
            to_evaluate = str(text).replace(':', '').replace('"', '').split()[1:]
            expression = " ".join(to_evaluate).strip()
            execute_if = True
            try:
                # If no argument left, return was None and statement is necessarily False
                if len(to_evaluate) == 0:
                    execute_if = False

                # If no comparator, check passed variable value
                elif len(to_evaluate) == 1:
                    LOG.debug(f"DM: No comparator, variable only: {to_evaluate[0]}")
                    if to_evaluate[0] and str(to_evaluate[0]).lower() in ("0", "false", "none", "null", "", "no"):
                        execute_if = False

                # This is some comparison, evaluate it
                else:
                    comparator = None
                    LOG.debug(f"DM: Evaluate comparison here: {to_evaluate}")
                    # comparator = to_evaluate[1]
                    comparators = self.string_comparators + self.math_comparators
                    # for i in ("==", "!=", ">", "<", "IN", "!IN", "CONTAINS"):

                    # Split equation into components
                    for i in comparators:
                        if i in to_evaluate:
                            comparator = i.strip()
                            break
                        elif f"!{i}" in to_evaluate:
                            comparator = f"!{i.strip()}"
                            break
                    LOG.debug(comparator)
                    LOG.debug(expression)
                    left_value, right_value = expression.split(comparator)
                    left_value = str(re.sub(", ", ",", left_value)).strip().lower().split(',')
                    right_value = str(re.sub(", ", ",", right_value)).strip().lower().split(',')
                    # left_value = str(left_value).strip()
                    # right_value = str(right_value).strip()
                    # This was temporary, fixed in _substitute_variables
                    # left_value = active_dict["variables"][left_value.strip().lstrip('{').rstrip('}')][0]
                    # right_value = active_dict["variables"][right_value.strip().lstrip('{').rstrip('}')]

                    LOG.debug(left_value)
                    LOG.debug(right_value)

                    LOG.debug(left_value[0].strip())
                    LOG.debug(right_value[0].strip())

                    try:
                        if left_value[0].strip().isnumeric():
                            left_as_int = int(left_value[0].strip())
                            right_as_int = int(right_value[0].strip())
                        else:
                            left_as_int = left_value[0].strip()
                            right_as_int = right_value[0].strip()
                    except Exception as e:
                        LOG.info(e)
                        left_as_int = left_value[0].strip()
                        right_as_int = right_value[0].strip()

                    if not comparator:
                        LOG.warning(f"no valid comparator found in {to_evaluate}")
                        execute_if = False
                    elif comparator == "==" and left_value[0].strip() != right_value[0].strip():
                        LOG.debug(f"not equal, go to else")
                        execute_if = False
                    elif comparator == "!=" and left_value[0].strip() == right_value[0].strip():
                        LOG.debug(f"equal, go to else")
                        execute_if = False
                    elif comparator == ">" and left_as_int <= right_as_int:
                        LOG.debug(f"less than or equal, go to else")
                        execute_if = False
                    elif comparator == "<" and left_as_int >= right_as_int:
                        LOG.debug(f"greater than or equal, go to else")
                        execute_if = False
                    elif comparator == ">=" and left_as_int < right_as_int:
                        LOG.debug(f"less than, go to else")
                        execute_if = False
                    elif comparator == "<=" and left_as_int > right_as_int:
                        LOG.debug(f"greater than, go to else")
                        execute_if = False

                    # String/List comparators are handled here
                    elif any(x for x in self.string_comparators if x in comparator):
                        # Catch error where right_value is a string
                        if isinstance(right_value, str) and ',' in right_value:
                            right_value = str(re.sub(", ", ",", right_value)).split(',')
                            LOG.warning(f"right_value was a string! now={right_value}")
                        elif isinstance(right_value, str):
                            right_value = [right_value]
                            LOG.warning(f"right_value was a string! now={right_value}")

                        if comparator == "IN" and str(left_value[0].strip()) not in right_value:
                            LOG.debug(f"not in, go to else")
                            execute_if = False
                        elif comparator == "!IN" and str(left_value[0].strip()) in right_value:
                            LOG.debug(f"in, go to else")
                            execute_if = False
                        elif comparator.endswith("CONTAINS"):  # Handle CONTAINS/!CONTAINS
                            LOG.debug(f"left={left_value}")
                            LOG.debug(f"right={right_value}")
                            contains = False
                            # Iterate over right_value items to find a match
                            for opt in right_value:
                                if f" {opt} " in f" {left_value[0]} ":
                                    LOG.info(f"Found {opt} in {left_value[0]}")
                                    contains = True
                                    break
                            if contains and comparator.startswith("!") or not contains:
                                execute_if = False
                        elif comparator.endswith("STARTSWITH"):
                            LOG.debug(f"left={left_value}")
                            LOG.debug(f"right={right_value}")
                            startswith = False
                            # Iterate over right_value items to find a match
                            for opt in right_value:
                                if left_value[0].startswith(opt):
                                    LOG.info(f"{left_value[0]} starts with {opt}")
                                    startswith = True
                                    break
                            if startswith and comparator.startswith("!") or not startswith:
                                execute_if = False
                        elif comparator.endswith("ENDSWITH"):
                            LOG.debug(f"left={left_value}")
                            LOG.debug(f"right={right_value}")
                            endswith = False
                            # Iterate over right_value items to find a match
                            for opt in right_value:
                                if left_value[0].endswith(opt):
                                    LOG.info(f"{left_value[0]} ends with {opt}")
                                    endswith = True
                                    break
                            if endswith and comparator.startswith("!") or not endswith:
                                execute_if = False
                    else:
                        LOG.debug(f"Statement is True")
            except Exception as e:
                LOG.error(e)

        # Update next index and save current indent
        active_dict = self.active_conversations[user].get_current_conversation()
        if_indent = active_dict["formatted_script"][active_dict["current_index"]]["indent"]
        active_dict["current_index"] += 1

        # Locate the else case or next line outside of if
        if not execute_if:
            LOG.info("LOCATING THE ELSE BLOCK")
            while active_dict["current_index"] <= len(active_dict["formatted_script"]):
                # Found an else at the same level, go to the following line
                if active_dict["formatted_script"][active_dict["current_index"]]["command"] == "else" and \
                        active_dict["formatted_script"][active_dict["current_index"]]["indent"] == if_indent:
                    LOG.debug(f'DM: Reached else: {active_dict["formatted_script"][active_dict["current_index"]]}')
                    active_dict["current_index"] += 1
                    break
                # Found an equally indented or outdented line that is NOT a comment, go here
                elif active_dict["formatted_script"][active_dict["current_index"]]["indent"] <= if_indent and \
                        active_dict["formatted_script"][active_dict["current_index"]]["command"]:
                    LOG.info(f'DM: Reached line outside of if, continue from '
                             f'here: {active_dict["formatted_script"][active_dict["current_index"]]}')
                    break
                else:
                    active_dict["current_index"] += 1
        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_else(self, user, text, message):
        """
        Called at script execution when an else line is encountered. This is only reached at the end of an "if", so this
        always results in finding the next line outside of the if/else condition
        :param user: nick on klat server, else "local"
        :param text: "else:"
        :param message: incoming messagebus Message
        """
        LOG.debug(f"DM: reached else case, continue ")
        active_dict = self.active_conversations[user].get_current_conversation()
        else_indent = active_dict["formatted_script"][active_dict["current_index"]]["indent"]
        active_dict["current_index"] += 1

        # Continue to iterate through formatted_script until end of else case
        while active_dict["formatted_script"][active_dict["current_index"]]["indent"] > else_indent:
            if active_dict["current_index"] == len(active_dict["formatted_script"]) - 1:
                LOG.warning("EOF reached evaluating case!")
                self._run_exit(user, text, message)
                break
            active_dict["current_index"] += 1

        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_sub_values(self, user, text, message):
        """
        Substitute substrings in a string variable
        :param user: nick on klat server, else "local"
        :param text: sub_values script line
        :param message: incoming messagebus Message
        """
        LOG.debug(text)
        active_dict = self.active_conversations[user].get_current_conversation()
        if '{' in text:
            # Value substitution
            key = text.split("{")[1].split("}")[0]
        elif '(' in text:
            # Variable function operator
            key = text.split("(")[1].split(")")[0]
        else:
            LOG.warning(f'Bad line at {active_dict["current_index"]}')
            key = text
        string_name, list_name = key.split(",")
        string_to_sub = " " + active_dict["variables"][string_name.strip()][0].lower() + " "
        substitution_pairs = active_dict["variables"][list_name.strip()]
        LOG.debug(string_to_sub)
        LOG.debug(substitution_pairs)
        for pair in substitution_pairs:
            LOG.debug(pair)
            if pair:
                if '" "' in pair:
                    raw, replacement = pair.lower().strip().split('" "', 1)
                else:
                    raw, replacement = pair.lower().strip().split(" ", 1)
                LOG.debug(f"Replace {raw} with {replacement}")
                if f"{raw}" in string_to_sub.split():
                    # TODO: Better methodology to prevent substring replacements DM
                    LOG.debug(f"found {raw}")
                    string_to_sub = string_to_sub.replace(f"{raw}", f"{replacement}")
                    # string_to_sub = string_to_sub.replace(f" {raw} ", f" {replacement} ")
            else:
                LOG.warning(f'Null element found in {list_name}: {substitution_pairs}')
        LOG.debug(string_to_sub)
        active_dict["variables"][string_name] = string_to_sub.strip()
        active_dict["current_index"] += 1
        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_sub_string(self, user, text, message):
        """
        Substitute a string variable with a different string
        :param user: nick on klat server, else "local"
        :param text: "else:"
        :param message: incoming messagebus Message
        """
        LOG.debug(f"DM: {text}")
        active_dict = self.active_conversations[user].get_current_conversation()

        # Parse out function arguments
        if '{' in text:
            key = text.split("{")[1].split("}")[0]
        elif '(' in text:
            key = text.split("(")[1].split(")")[0]
        else:
            LOG.warning(f'Bad line at {active_dict["current_index"]}')
            key = text
        string_name, list_name = key.split(",")
        input_string_to_sub = " " + active_dict["variables"][string_name.strip()] + " "
        substitution_pairs = active_dict["variables"][list_name.strip()]
        # variables_in_response = []
        output_string = None
        LOG.debug(input_string_to_sub)
        LOG.debug(len(substitution_pairs))

########################################################################################################################
        # Line is parsed, input string and sub pairs have been extracted

        # Iterate over substitution pairs
        for pattern in substitution_pairs:
            pattern = pattern.strip().replace('" "', '""')
            LOG.debug(pattern)
            if pattern:
                if pattern not in active_dict["sub_string_counters"].keys():
                    active_dict["sub_string_counters"][pattern] = 0

                try:
                    # Parse string substitutions
                    responses = list(str(pattern).split('"'))
                    # LOG.debug(responses)  # ['', 'i remember *', ' ', 'Do you think of * often?', '']
                    responses = list(filter(None, responses))
                    # LOG.debug(responses)
                    pattern_to_match = normalize(responses.pop(0))
                    # LOG.debug(responses)  # ["Please don't apologize about *"]
                    # LOG.debug(pattern_to_match)
                    # for part in responses:
                    #     LOG.debug(part)
                except Exception as e:
                    LOG.error(e)
                    responses = None
                    pattern_to_match = None
                # try:
                #     for opt in pattern.split:
                #
                #     _, pattern_to_match, _, output_string_to_sub, _ = pattern.split('"')
                # except Exception as e:
                #     LOG.error(e)
                #     pattern_to_match, output_string_to_sub = pattern.strip().split(" ", 1)
                # match = match.replace('"', '')
                # LOG.debug(f"match={pattern_to_match}| responses={responses}")
                search_pattern = pattern_to_match.strip()

                # Check if match has a string substitution and replace with named variables
                parts = pattern_to_match.split()
                if '*' in parts:
                    i = 1
                    for part in parts:
                        # Replace any wildcards with numbered variables
                        if part == "*":
                            parts[parts.index(part)] = '{_wildcard_' + str(i) + '}'
                            i += 1
                    # while "*" in output_string_to_sub.split():
                    #     output_string_to_sub = output_string_to_sub.replace('*', ' {_wildcard_' + str(i) + '}', 1)
                    #     i += 1
                    pattern_to_match = " ".join(parts)
                    LOG.debug(pattern_to_match)

                # Split parts at variables
                if '{' in pattern_to_match:
                    search_pattern = []
                    parts = pattern_to_match.split('{')
                    # LOG.debug(parts)
                    # Parse out variable names and remove them from search string
                    for part in parts:
                        try:
                            # This part has a variable in it
                            if '}' in part:
                                variable, remainder = part.split('}')
                                # LOG.debug(variable)
                                # variables_in_response.append(variable)
                                # search_string = search_string.replace('{' + variable + '}', '^^')
                                # Add in variable element
                                search_pattern.append('{' + variable + '}')
                                # Add in text following variable
                                search_pattern.append(remainder)
                            # This should never happen
                            else:
                                search_pattern.append(part)
                        except Exception as e:
                            LOG.warning(e)
                    # LOG.debug(search_pattern)
                    # search_string = search_string.split("^^")

                # Split parts at synonyms
                if "[" in pattern_to_match:
                    # LOG.debug("Synonym to check")
                    if isinstance(search_pattern, str):
                        parts = search_pattern.split('[')
                        search_pattern = []
                        for part in parts:
                            if ']' in part:
                                variable, remainder = part.split(']')
                                # LOG.debug(variable)
                                # variables_in_response.append(variable)
                                # search_string = search_string.replace('{' + variable + '}', '^^')
                                # Add in variable element
                                search_pattern.append('[' + variable + ']')
                                # Add in text following variable
                                search_pattern.append(remainder)
                            else:
                                search_pattern.append(part)
                        pass
                    else:
                        temp_list = search_pattern
                        search_pattern = []
                        # Iterate over pre-split parts and look for synonym elements
                        for part in temp_list:
                            # Split out synonyms
                            if '[' in part:
                                prefix, remainder = part.split('[', 1)
                                # Append string before synonym element
                                if prefix.strip():
                                    search_pattern.append(prefix.strip())
                                variable, remainder = remainder.split(']', 1)
                                # LOG.debug(variable)
                                # Add in variable element
                                search_pattern.append('[' + variable + ']')
                                # Append string after synonym element
                                if remainder:
                                    search_pattern.append(remainder.strip())
                            # Catch empty splits
                            elif part:
                                search_pattern.append(part)
                # else:
                #     search_pattern = pattern_to_match.strip()

                LOG.debug(search_pattern)
                # Catch empty parts
                for part in search_pattern:
                    if part == '':
                        search_pattern.remove(part)
                LOG.debug(f"looking for {search_pattern} in {input_string_to_sub}")

                # Find first matched substitution
                # for substring in search_string:
                #     LOG.debug(substring)
                #     if substring.lower() in input_string_to_sub:
                #         LOG.debug("PASS")
                #     else:
                #         LOG.debug("FAIL")

########################################################################################################################
                # Evaluate any synonym patterns in our string
                synonyms_matched = True
                if '[' in pattern_to_match:
                    while '[' in pattern_to_match:
                        syn_to_evaluate, pattern_to_match = pattern_to_match.split('[', 1)[1].split(']', 1)
                        LOG.debug(syn_to_evaluate)
                        # LOG.debug(active_dict["variables"][syn_to_evaluate].split(','))
                        # Check if none of the synonyms are in our input string
                        if not any(syn.lower().strip() in input_string_to_sub for syn in
                                   active_dict["variables"][syn_to_evaluate]):
                            LOG.debug("Synonym not matched")
                            synonyms_matched = False
                            break
                        # else:
                        #     input_string_to_sub = input_string_to_sub.replace("something", syn_to_evaluate)

                input_string_to_sub = normalize(input_string_to_sub)
                LOG.debug(input_string_to_sub)
                # Check if our pattern is matched/Response is found
                if (isinstance(search_pattern, str) and search_pattern in input_string_to_sub) or (
                        (isinstance(search_pattern, list) and
                         all(substring.lower() in input_string_to_sub for substring in search_pattern if (
                                 substring and '{' not in substring
                                 and '[' not in substring and '*' not in substring)))) and synonyms_matched:
                    # Assume this response is valid (may not be because of synonym position)
                    valid_response = True
                    LOG.info(f">>>Matched: {pattern_to_match}")
                    # Get index of response to use
                    response_index = active_dict["sub_string_counters"].get(pattern, 0)
                    LOG.debug(response_index)
                    # Catch out of bounds index and loop back to 0
                    if response_index >= len(responses):
                        response_index = 0
                    # Get chosen response and increment counter
                    output_string_to_sub = responses[response_index]
                    active_dict["sub_string_counters"][pattern] = response_index + 1

                    # Handle wildcard variable names in output string
                    parts = output_string_to_sub.split()
                    if '*' in parts:
                        i = 1
                        for part in parts:
                            # Replace any wildcards with numbered variables
                            if part == "*":
                                parts[parts.index(part)] = '{_wildcard_' + str(i) + '}'
                                i += 1
                        # while "*" in output_string_to_sub.split():
                        #     output_string_to_sub = output_string_to_sub.replace('*', ' {_wildcard_' + str(i) + '}', 1)
                        #     i += 1
                    output_string_to_sub = " ".join(parts)
                    LOG.debug(output_string_to_sub)

                    # output_string = output_string_to_sub

                    input_to_keep = None
                    # if '*' in pattern_to_match:
                    #     pattern_to_match = pattern_to_match.lower()
                    #     if pattern_to_match == "*":
                    #         LOG.debug(input_string_to_sub)
                    #         LOG.debug(output_string_to_sub)
                    #         input_to_keep = input_string_to_sub
                    #     elif pattern_to_match.startswith('*'):
                    #         input_split_point = pattern_to_match.split('*')[1]
                    #         LOG.debug(input_split_point)
                    #         input_to_keep = input_string_to_sub.split(input_split_point)[0]
                    #         LOG.debug(input_to_keep)
                    #     elif pattern_to_match.endswith('*'):
                    #         input_split_point = pattern_to_match.split('*')[0]
                    #         LOG.debug(input_split_point)
                    #         input_to_keep = input_string_to_sub.split(input_split_point)[1]
                    #         LOG.debug(input_to_keep)
                    #     else:
                    #         left_strip, right_strip = pattern_to_match.split('*')
                    #         input_to_keep = input_string_to_sub.split(left_strip)[1].split(right_strip)[0]
                    #         LOG.debug(input_to_keep)

                    # LOG.debug(output_string_to_sub)
                    # if '*' in output_string_to_sub and input_to_keep:
                    #     output_string = output_string_to_sub
                    #     LOG.debug(output_string)
                    #     output_string = output_string.replace('*', input_to_keep)
                    #     LOG.debug(output_string)
                    # else:
                    #     output_string = output_string_to_sub

                    # Iterate over input string
                    LOG.debug(f"search {search_pattern}")
                    LOG.debug(f"input  {input_string_to_sub}")
                    try:
                        modified_input = input_string_to_sub.strip()
                        next_var_to_fill = None

                        # Iterate over all string elements in our search pattern
                        for segment in search_pattern:
                            # Break if the previous synonym evaluation failed
                            if not synonyms_matched:
                                LOG.debug("Breaking on unmatched synonym")
                                valid_response = False
                                break
                            LOG.debug(segment)
                            # Check that the substring is not empty (edge case)
                            if segment:
                                # There is a list variable to match
                                if '[' in segment:
                                    LOG.debug(segment)  # This may have other text to match
                                    var_to_match = segment.split('[')[1].split(']')[0].strip()
                                    LOG.debug(var_to_match)
                                    strings_to_match = active_dict["variables"][var_to_match]  # .split(',')
                                    LOG.debug(strings_to_match)
                                    synonym_matched = False
                                    for string_to_match in strings_to_match:
                                        string_to_match = string_to_match.strip()
                                        LOG.debug(string_to_match)
                                        test_start = segment.replace(f"[{var_to_match}]", string_to_match).strip()
                                        LOG.debug(f"Check if {modified_input.strip()} starts with {test_start}")
                                        # LOG.debug(test_start)
                                        if modified_input.strip().startswith(test_start):
                                            LOG.debug("Synonym Matched!")
                                            # Add synonym to vars with extra chars to prevent conflicting variable names
                                            LOG.debug(f"_{var_to_match}_ = {string_to_match}")
                                            active_dict["variables"][f"_{var_to_match}_"] = [string_to_match]
                                            synonym_matched = True
                                            LOG.debug(f"{modified_input} | {test_start}")
                                            modified_input = modified_input.split(test_start, 1)[1]
                                            break
                                    if not synonym_matched:
                                        LOG.info("synonyms not positionally matched")
                                        valid_response = False
                                        break

                                # If we are at a variable in our search string
                                elif '{' in segment:
                                    LOG.debug(segment)
                                    next_var_to_fill = segment.split('{')[1].split('}')[0]
                                    LOG.debug(next_var_to_fill)

                                    # If this is the last part of the line, assign the variable here
                                    if search_pattern.index(segment) == len(search_pattern) - 1:
                                        LOG.debug(f"{next_var_to_fill} prepend {modified_input}")
                                        value = modified_input.strip()
                                        to_update = active_dict["variables"].get(next_var_to_fill)

                                        # Push new value to front of list
                                        if to_update and isinstance(to_update, list):
                                            active_dict["variables"][next_var_to_fill].insert(0, value)
                                        elif to_update:
                                            active_dict["variables"][next_var_to_fill] = [value, to_update]
                                        else:
                                            active_dict["variables"][next_var_to_fill] = [value]
                                        LOG.debug(f'{next_var_to_fill}={active_dict["variables"][next_var_to_fill]}')

                                        # if next_var_to_fill not in active_dict["variables"]:
                                        #     active_dict["variables"][next_var_to_fill] = []
                                        # new_val = \
                                        #     [value] + list(active_dict["variables"][next_var_to_fill])
                                        # LOG.debug(new_val)
                                        # active_dict["variables"][next_var_to_fill] = new_val

                                # # If we are at a wildcard in our search string
                                # elif '*' in substr:
                                #     pass

                                # Else we have a regular string to match
                                else:
                                    # Check if we have a variable to fill with the input before this match
                                    if next_var_to_fill:
                                        # Make sure variable is initialized
                                        # if next_var_to_fill not in active_dict["variables"]:
                                        #     active_dict["variables"][next_var_to_fill] = []

                                        LOG.debug(modified_input)
                                        value = f" {modified_input.split(segment, 1)[0].strip()} "
                                        LOG.debug(f"perspective change for: {value}")
                                        for perspective, replacement in self.perspective_changes.items():
                                            value = value.replace(perspective, replacement).strip()
                                        LOG.debug(f"{next_var_to_fill} prepend {value}")

                                        to_update = active_dict["variables"].get(next_var_to_fill)

                                        # Push new value to front of list
                                        if to_update and isinstance(to_update, list):
                                            active_dict["variables"][next_var_to_fill].insert(0, value)
                                        elif to_update:
                                            active_dict["variables"][next_var_to_fill] = [value, to_update]
                                        else:
                                            active_dict["variables"][next_var_to_fill] = [value]

                                        # if value:
                                        #     new_val = \
                                        #         [value] + list(active_dict["variables"][next_var_to_fill])
                                        #     LOG.debug(new_val)
                                        #     active_dict["variables"][next_var_to_fill] = new_val
                                        next_var_to_fill = None
                                    # Split our input string to remove the text in our search pattern
                                    modified_input = modified_input.split(segment, 1)[1]
                                    LOG.debug(modified_input)
                            # If we reached the end of the search pattern and have a variable, take the end of the input
                            elif next_var_to_fill:
                                # Make sure variable is initialized
                                # if next_var_to_fill not in active_dict["variables"]:
                                #     active_dict["variables"][next_var_to_fill] = []

                                LOG.debug(f"perspective change for: {modified_input}")
                                modified_input = f" {modified_input} "
                                for perspective, replacement in self.perspective_changes.items():
                                    modified_input = modified_input.replace(perspective, replacement)
                                LOG.debug(f"{next_var_to_fill} prepend {modified_input.strip()}")
                                to_update = active_dict["variables"].get(next_var_to_fill)

                                # Push new value to front of list
                                if to_update and isinstance(to_update, list):
                                    active_dict["variables"][next_var_to_fill].insert(0, modified_input.strip())
                                elif to_update:
                                    active_dict["variables"][next_var_to_fill] = [modified_input.strip(), to_update]
                                else:
                                    active_dict["variables"][next_var_to_fill] = [modified_input.strip()]

                                # new_val = [modified_input.strip()] + list(active_dict["variables"][next_var_to_fill])
                                # LOG.debug(new_val)
                                # active_dict["variables"][next_var_to_fill] = new_val
                    except Exception as e:
                        LOG.error(e)
                    if valid_response:
                        LOG.debug("Valid response found!")
                        LOG.debug(len(active_dict["variables"]))
                        LOG.debug(output_string_to_sub)

                        output_string = self._substitute_variables(user, output_string_to_sub, message, True)
                        LOG.debug(input_to_keep)
                        LOG.debug(output_string)
                        # if '*' in output_string and input_to_keep:
                        #     output_string = output_string.replace('*', input_to_keep)
                        # LOG.debug(output_string)

                        # # Do named variable substitution
                        # elif '{' in pattern_to_match:
                        #     # LOG.debug(variables_in_response)

                        # # Check that pattern_to_match
                        # matched = True
                        # input_to_check = input_string_to_sub.split('{')
                        # if parts:
                        #     for part in parts:
                        #         LOG.debug(part)
                        #         if part in pattern_to_match:
                        #             input_to_check = input_to_check.remove(part)
                        #         else:
                        #             matched = False
                        #             break
                        # if matched:
                        #     input_to_check = input_to_check.split()
                        #     LOG.debug(input_to_check)
                        # to_return, input_to_substitute = None, None
                        # for var in variables_in_response:
                        #     LOG.debug(f"looking for {var}")
                        #     if '{' + var + '}' in pattern_to_match:
                        #         LOG.debug(f"{var} found in {pattern_to_match}")
                        #         input_prefix, input_suffix = pattern_to_match.split('{' + var + '}')
                        #         LOG.debug(input_prefix)
                        #         LOG.debug(input_suffix)
                        #         input_to_substitute = input_string_to_sub.replace(input_prefix, "")\
                        #             .replace(input_suffix, "")
                        #         LOG.debug(input_to_substitute)
                        #         to_return = replacement.replace('{' + var + '}', input_to_substitute)
                        #         LOG.debug(to_return)
                        # This means we matched something
                        # if to_return and to_return != input_to_substitute:
                        #     input_string_to_sub = to_return
                        #     break

                        # Simple response with no substitution
                        # else:
                        #     LOG.debug(input_string_to_sub)
                        #     LOG.debug(output_string_to_sub)
                        #     output_string = output_string_to_sub
                        break
                    else:
                        LOG.debug(">>>Response not valid, continue evaluating responses")
        # Update variable and continue
        # LOG.debug(modified_input)
        LOG.debug(output_string)
        # try:
        #     new_val = [output_string.strip()] + list(active_dict["variables"][string_name])
        # except Exception as e:
        #     LOG.error(e)
        #     new_val = [output_string.strip()]
        #
        # LOG.debug(new_val)
        # active_dict["variables"][string_name] = new_val
        value = output_string.strip()
        to_update = active_dict["variables"].get(string_name)

        # Push new value to front of list
        if to_update and isinstance(to_update, list):
            active_dict["variables"][string_name].insert(0, value)
        elif to_update:
            active_dict["variables"][string_name] = [value, to_update]
        else:
            active_dict["variables"][string_name] = [value]

        active_dict["current_index"] += 1

        # The variable is updated, now just continue the script
        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_set(self, user, text, message):
        """
        Set variable values to static values at script runtime. String substitutions done in text at this point
        :param user: nick on klat server, else "local"
        :param text: variable = value
        :param message: incoming messagebus Message
        """
        LOG.debug(text)
        active_dict = self.active_conversations[user].get_current_conversation()

        parser_data = message.data.get("parser_data")
        if parser_data:
            var = parser_data.get("variable").strip()
            val = parser_data.get("value").strip()
        else:
            # Determine variables and values
            var, val = text.split('=', 1)
            var = var.strip().lstrip('{').rstrip('}')
            val = val.strip()
        to_update = active_dict["variables"].get(var, None)

        # Parse new val into a list
        # TODO: Better parsing of quoted strings here DM
        if "," in val and not (val.startswith('"') or val.startswith("'")):
            value = val.replace(", ", ",").split(",")
        else:
            value = [val]

        # Check if there is a function call in this assignment
        for opt in self.variable_functions:
            # LOG.debug(f"looking for {opt} in {val}")
            # If we find an option, process it and stop looking for more options
            if opt in val:
                LOG.debug(f"found {opt} in {val}")
                if '{' in str(val):
                    val = str(val).split('{')[1].split('}')[0]
                elif '(' in str(val):
                    val = str(val).split('(')[1].split(')')[0]
                value = self.variable_functions[opt](val, user, None)
                LOG.debug(type(value))
                if isinstance(value, str):
                    value = [value.split(',')[0]]
                LOG.debug(value)

                break

        LOG.debug(f"After parsing opts: {var} = {value}")

        # LOG.debug(f"update var: {var} = {to_update} to include {value}")

        # Push new value to front of list
        if isinstance(to_update, list):
            # Add on previous values if any exist (catches list of nulls and prevents keeping them)
            if any(x for x in to_update if x):
                value.extend(to_update)
            # active_dict["variables"][var.strip()] = value
        elif to_update:
            value.extend([to_update])
            # active_dict["variables"][var.strip()] = value.extend([to_update])  #[val.strip(), to_update]
        else:
            LOG.debug(f"Requested to update empty variable: {var}")
        # TODO: Handle var here as profile value (i.e. user.email = something)
        #       Maybe have Neon notify user to prevent hidden script functionality DM
        active_dict["variables"][var] = value  # [val.strip()]

        LOG.debug(f'{var} = {active_dict["variables"][var][0]}')
        active_dict["current_index"] += 1
        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_reconvey(self, user, text, message):
        """
        Handle a reconvey script command
        :param user: nick on klat server, else "local"
        :param text: variable to find associated utterance for
        :param message: incoming messagebus Message
        """
        LOG.info(f"RECONVEY ENTERED for {user} with {text} ")
        LOG.info(f"DM: {text}")
        LOG.info(message.data.get("parser_data"))
        active_dict = self.active_conversations[user].get_current_conversation()
        audio = None
        if message.data.get("parser_data"):
            parser_data = message.data.get("parser_data")
            to_reconvey = parser_data.get("reconvey_text")
            name = clean_quotes(parser_data.get("name", "Neon"))
            # name = clean_quotes(name)  # TODO: Handle name as variable here DM
            if '"' in to_reconvey or "'" in to_reconvey:
                text = clean_quotes(to_reconvey)
            else:
                text = active_dict["variables"].get(to_reconvey, [text])[0]
            if parser_data.get("reconvey_file"):
                if '"' in to_reconvey or "'" in to_reconvey:
                    audio = clean_quotes(parser_data.get("reconvey_file"))
                else:
                    audio = active_dict["variables"].get(parser_data["reconvey_file"], [text])[0]
                if not audio.startswith("http"):
                    # Try handling as an absolute path
                    audio = os.path.expanduser(audio)
                    if not os.path.isfile(audio):
                        script_title = active_dict["script_meta"].get("title", active_dict["script_filename"])
                        dir_name = script_title.strip('"').lower().replace(" ", "_")

                        # Try handling as a relative path in the skill
                        audio = os.path.join(self.audio_location, dir_name, audio)
                        if not os.path.isfile(audio):
                            LOG.debug(f"Didn't resolve audio file: {audio}")

                            # Try to resolve in skill audio directory
                            if os.path.isdir(os.path.join(self.audio_location, dir_name)):
                                LOG.debug(f"search for: {os.path.basename(audio)}")
                                for file in os.listdir(os.path.join(self.audio_location, dir_name)):
                                    if audio and os.path.splitext(file)[0].strip() == os.path.basename(audio).strip():
                                        audio = os.path.join(self.audio_location, dir_name, file)
                                        LOG.info(f"Resolved Audio: {audio}")
                                        break
                    if not os.path.isfile(audio):
                        audio = active_dict["audio_responses"].get(to_reconvey, [""])[0]
        else:
            # This is original behavior, no parameters have been pre-parsed
            var_to_speak = text
            name = "Neon"
            LOG.debug(f"var_to_speak={var_to_speak}")
            # Playback audio file if available
            if active_dict["audio_responses"].get(var_to_speak, None):
                # This should be some file in the transcripts directory
                LOG.debug(active_dict["audio_responses"][var_to_speak])
                text = active_dict["variables"][var_to_speak][0]
                audio = active_dict["audio_responses"][var_to_speak][0]

            # Just speak variable value if no audio is available
            else:
                text = active_dict["variables"][var_to_speak][0]
                audio = None
                try:
                    LOG.debug(f'About to speak {active_dict["variables"][var_to_speak][0]}')
                    self.speak(active_dict["variables"][var_to_speak][0])
                except Exception as e:
                    LOG.error(e)
            LOG.debug(active_dict["variables"])

        # Do actual playback
        if message.context.get("klat_data"):
            # Example Filename
            # /home/guydaniels1953/NeonAI/NGI/Documents/NeonGecko/ts_transcript_audio_segments/
            # daniel-2020-07-07/daniel-2020-07-07 20:33:37.034829 just kidding .wav'

            # signal_name = build_signal_name(user, text)
            # self.create_signal(signal_name)
            # message.context["cc_data"]["signal_to_check"] = signal_name
            if audio:
                self.send_with_audio(text, audio, message,
                                     speaker={"name": name, "language": None, "gender": None, "voice": None})
            else:
                LOG.error(f"Reconvey audio not found!")
                speaker_data = active_dict["speaker_data"]
                speaker_data["name"] = name
                to_speak = build_message("neon speak", text, message, speaker_data)
                self.speak(text, message=to_speak)
        else:
            if request_from_mobile(message):
                # TODO: Handle sending audio data to mobile (non-server so can't assume public URL) DM
                pass
            else:
                if os.path.isfile(audio):
                    # Skills will not block while speaking, so wait here to make sure reconveyed audio doesn't overlap
                    wait_while_speaking()
                    LOG.info(f"The audio path is {audio}")
                    process = play_audio_file(audio)
                    while process and process.poll() is None:
                        time.sleep(0.2)
                    LOG.info(f"Should have played {audio}")
                else:
                    LOG.error(f"Audio file not found! {audio}")
                    self.speak(text)
        active_dict["current_index"] += 1

    def _run_email(self, user, content, message):
        """
        Send an email with the specified subject and body
        :param user   : nick on klat server, else "local"
        :param content: title and body variable names
        :param message: incoming messagebus Message

        """
        LOG.debug(f"DM: {content}")
        active_dict = self.active_conversations[user].get_current_conversation()

        email_addr = get_user_prefs(message)["user"].get("email")

        parser_data = message.data.get("parser_data")
        if parser_data:
            title = parser_data.get("subject")
            body = parser_data.get("body")
        else:
            title_var, body_var = content.split(",")
            LOG.debug(f"title={title_var}, body={body_var}")
            LOG.debug(active_dict["variables"])
            if title_var.startswith('"') or title_var.startswith("'"):
                title = title_var.strip('"').strip("'")
            else:
                title = active_dict["variables"].get(title_var.strip(), [title_var])[0].strip('"')
            if body_var.startswith('"') or body_var.startswith("'"):
                body = body_var.strip('"').strip("'")
            else:
                body = active_dict["variables"].get(body_var.strip(), ["Body variable was not defined."])[0]\
                    .strip('"').replace("\\n", "\n")

        if not email_addr:
            self.speak_dialog("no_email", private=True)
        else:
            LOG.debug(f"sending: {title}")
            self.send_email(title, body, message, email_addr)
            # self.bus.emit(Message("neon.email", {"title": title, "email": email_addr, "body": body}))

        active_dict["current_index"] += 1
        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_language(self, user, content, message):
        """
        Handles a 'Language' line at runtime. Existing speaker data is overwritten with the content passed here
        :param user   : nick on klat server, else "local"
        :param content: speaker string to parse (i.e. "female en-us", "en-au male", "en-gb")
        :param message: incoming messagebus Message
        """
        LOG.debug(f"DM: {content}")
        active_dict = self.active_conversations[user].get_current_conversation()

        if message.data.get("parser_data") and any((message.data["parser_data"].get("language"),
                                                    message.data["parser_data"].get("gender"))):
            language = message.data["parser_data"].get("language", get_user_prefs(message)["speech"]["tts_language"])
            gender = message.data["parser_data"].get("gender", get_user_prefs(message)["speech"].get("tts_gender"))
            active_dict["speaker_data"] = {"name": "Neon",
                                           "language": language,
                                           "gender": gender,
                                           "override_user": True}
        else:
            line = re.sub('"', '', str(content)).split()
            LOG.debug(line)
            if "male" in line:
                line.remove("male")
                gender = "male"
            elif "female" in line:
                line.remove("female")
                gender = "female"
            else:
                LOG.warning("No gender specified in Language line!")
                try:
                    gender = get_user_prefs(message)["speech"].get("tts_gender", "female")
                    LOG.debug(f"Got user preferred gender: {gender}")
                except Exception as e:
                    LOG.error(e)
                    gender = "female"

            LOG.debug(line)
            language = line[0].lower().strip('"').strip("'").rstrip(",") or get_user_prefs(message)["speech"]

            active_dict["speaker_data"] = active_dict["speaker_data"] or {}
            active_dict["speaker_data"]["language"] = language
            active_dict["speaker_data"]["gender"] = gender

        active_dict["current_index"] += 1
        # LOG.debug(f"DM: Continue Script Execution Call")
        # self._continue_script_execution(message, user)

    def _run_new_script(self, user, content, message):
        """
        Run a new script and handle existing script variables for this script to be resumed
        :param user   : nick on klat server, else "local"
        :param content: script filename to run
        :param message: incoming messagebus Message
        """
        # TODO: check this implementation thoroughly
        LOG.debug(f"content={content}")

        filename = content.strip()
        speak_name = filename.replace("_", " ")
        filename = filename.replace(" ", "_")
        if self._script_file_exists(filename):
            cache = self.get_cached_data(filename + self.file_ext, os.path.join(self.__location__, "script_txt"))
            old_dict = deepcopy(self.active_conversations[user].get_current_conversation())
            old_dict["current_index"] += 1
            script_meta = cache[9]
            self._init_conversation(user, script_meta=script_meta, script_filename=filename)
            new_dict = self.active_conversations[user].get_current_conversation()
            # new_dict["script_filename"] = filename
            new_dict["formatted_script"] = cache[0]
            new_dict["speaker_data"] = cache[1]
            new_dict["variables"] = cache[2]
            new_dict["loops_dict"] = cache[3]
            new_dict["goto_tags"] = cache[4]
            new_dict["timeout"] = cache[5]
            new_dict["timeout_action"] = cache[6]
            # new_dict = self._load_to_cache(new_dict, speak_name, user)
            new_dict["pending_scripts"].insert(0, old_dict)
            LOG.debug(f"DM: {new_dict}")
            # self.create_signal(f"{user}_CC_active")
        else:
            self.speak_dialog("NotFound", {"file_to_open": speak_name})
            self.active_conversations[user].get_current_conversation()["current_index"] += 1
        # self._continue_script_execution(message, user)

    def _run_variable(self, user, text, message):
        """
        Handle variable value determination at runtime
        :param user   : nick on klat server, else "local"
        :param text   : variable line text
        :param message: incoming messagebus Message
        :return:
        """
        active_dict = self.active_conversations[user].get_current_conversation()

        parser_data = message.data.get("parser_data")
        LOG.info(f"PARSER DATA IS {parser_data}")
        LOG.debug(text)
        LOG.debug(parser_data)
        key, value = None, None
        if parser_data:
            key = parser_data.get("variable_name")
            value = parser_data.get("variable_value")

        if not value:
            LOG.info(f"No value parsed for line: {text}")
            if "=" in text and "{" not in text.split("=")[0]:  # This is a work-around for table_scraped dicts
                key, value = text.split("=", 1)
            elif ":" in text:
                key, value = text.split(":", 1)
            # else:
            #     key, value = None, text

        if key:
            LOG.info(f"KEY {key} HAS VALUE {value}")
            # Trim whitespace
            key = key.strip()
            if value:
                value = value.strip()
            else:
                value = ""
            for opt in self.variable_functions:
                LOG.debug(f"looking for {opt} in {value}")

                # If we find an option, process it and stop looking for more options
                if value.startswith(opt):
                    # LOG.debug(f"found {opt} in {value}")
                    if '{' in str(value):
                        LOG.warning("This syntax is depreciated, please use '()' to wrap function arguments")
                        val = str(value).split('{')[1].split('}')[0]
                    elif '(' in str(value):
                        val = str(value).split('(')[1].split(')')[0]
                    else:
                        val = value
                    value = self.variable_functions[opt](val, user, None)
                    # LOG.debug(type(value))
                    if isinstance(value, str):
                        if ',' in value:
                            value = value.split(',')[1]
                        else:
                            value = [value]
                    # LOG.debug(value)

                    # LOG.debug(type(value))

                    break

            if not active_dict["variables"][key]:
                active_dict["variables"][key] = []

            LOG.debug(value)
            if isinstance(value, list):
                if not any([i for i in value if ':' in i]):
                    # Standard list of values
                    LOG.debug(active_dict["variables"])
                    active_dict["variables"][key].extend(value)
                    LOG.debug(active_dict["variables"])
                else:
                    # list of key/value pairs, parse to dict
                    LOG.debug(active_dict["variables"])
                    active_dict["variables"][key].append({i.split(": ")[0]: i.split(": ")[1] for i in value})
                    LOG.debug(active_dict["variables"])
            elif isinstance(value, dict):
                # Dict
                LOG.debug(active_dict["variables"])
                active_dict["variables"][key].append(value)
                LOG.debug(active_dict["variables"])
            elif value.startswith("{") and value.endswith("}"):
                from ast import literal_eval
                active_dict["variables"][key].append(literal_eval(value))
                LOG.debug(active_dict["variables"])
            else:
                # String/Int, parse to list
                LOG.debug(active_dict["variables"])
                if "," in value:
                    value = value.replace(", ", ",").strip().split(",")
                else:
                    value = [value.strip()]
                active_dict["variables"][key].extend(value)
                LOG.debug(active_dict["variables"])
        else:
            LOG.warning(f"Variable line with no value: {text}")
        active_dict["current_index"] += 1
        # self._continue_script_execution(message, user)

    # Variable value assignment (at runtime)
    def _variable_voice_input(self, var_to_fill, user, message=None):
        """
        Called when voice_input is encountered during script execution. Prepares for the next user utterance to fill the
        passed variable name
        :param var_to_fill: argument in script parentheses (name of variable to be filled with next voice input)
        :param user: nick on klat server, else "local"
        """
        LOG.debug(message)
        self.awaiting_input.append(user)
        LOG.info(f"Voice input needed for {user} to assign {var_to_fill}")
        if not var_to_fill:
            LOG.warning(f"Requested voice_input with null variable!")
        LOG.info(var_to_fill)
        LOG.info(user)

        if ',' in var_to_fill:
            var_to_fill, var_options = var_to_fill.split(',', 1)
        # LOG.debug(var_options)
        active_dict = self.active_conversations[user].get_current_conversation()
        active_dict["variable_to_fill"] = var_to_fill
        LOG.info(f"__variable_voice_input successfully executed for {user} with {var_to_fill}")

    def _variable_select_one(self, key, user, message=None):
        """
        Called at script execution to return a formatted string of available variable options to be spoken. The user
        response must be in these options to be considered valid.
        :param key: variable name to lookup
        :param user: nick on klat server, else "local"
        :return: formatted string to be spoken
        """
        # LOG.debug(f"DM {key}, {user}")
        # LOG.debug(key)
        # LOG.debug(user)
        LOG.debug(message)
        try:
            variable_key = key.replace(list(self.variable_functions.keys())[0], '')
            active_dict = self.active_conversations[user].get_current_conversation()
            LOG.debug(variable_key)
            LOG.info(active_dict["variables"][variable_key])
            temp_item = f'or {active_dict["variables"][variable_key][-1]}'
            LOG.debug(f'one of the following: {", ".join(active_dict["variables"][variable_key][:-1])}, {temp_item}')
            # self.create_signal(f"{user}_CC_choosingValue")
            # active_dict["selection_required"] = variable_key
            return f'one of the following: {", ".join(active_dict["variables"][variable_key][:-1])}, {temp_item}'
        except Exception as e:
            LOG.error(e)
            return ""
        # return self.selection_made

    def _variable_table_scrape_to_dict(self, key, user, message=None):
        """
        Compiles a webpage containing links into a dictionary of link names to URLs.
        :param key: variable name to populate
        :param user: nick on klat server, else "local"
        """
        LOG.debug(message)
        # LOG.debug(f"{key}, {user}")
        # LOG.info(key)
        # LOG.info(user)
        active_dict = self.active_conversations[user].get_current_conversation()
        LOG.debug(list(active_dict["variables"].items()))
        # reverse_value = {v[0]: k for k, v in list(active_dict["variables"].items())}
        # LOG.debug(reverse_value)

        if isinstance(key, list):
            #     pass
            # elif isinstance(key, list) and len(key) == 1:
            key = key[0]

        try:
            # Parse URL out of script line and scrape that page
            # url = key.split('(')[1][:-1].replace('"', '').replace("'", "")
            url = key
            LOG.debug(url)
            available_links = scrape(url)
            # LOG.debug("scrape done.")
            LOG.debug(f"Scraped: {available_links}")
            # active_dict["variables"][key_to_update] = available_links
            return available_links
        except Exception as e:
            LOG.error(e)
            self._run_exit(user, "", message)

    def _variable_random_select(self, key, user, message=None):
        """
        Called at script execution to return a formatted string of a random selection of variable options to be spoken.
        :param key: variable name to lookup
        :param user: nick on klat server, else "local"
        :return: formatted string to be spoken
        """
        LOG.debug(message)
        try:
            LOG.debug(f"{key}, {user}")
            # key = key.replace("random", '')
            active_dict = self.active_conversations[user].get_current_conversation()
            # LOG.debug(active_dict)
            LOG.debug(f'Looking for {key} in {active_dict["variables"]}')
            LOG.debug(active_dict["variables"][key])  # List to select from
            # try:
            #     internal_functions = [i for i in self.variable_functions.keys() for x
            #                           in active_dict["variables"][key] if i in x]
            #     if internal_functions:
            #         LOG.debug(internal_functions)
            #         self.variable_functions[internal_functions[0]](active_dict["variables"][key], user)
            # except Exception as e:
            #     LOG.error(e)
            LOG.debug(f'DM: {type(active_dict["variables"][key][0])}')
            if isinstance(active_dict["variables"][key][0], str):
                try:
                    random_items = random.sample(active_dict["variables"][key], 3)
                    LOG.debug(random_items)
                    return f'{random_items[0]}, {random_items[1]}, or {random_items[2]}'
                except ValueError:
                    return f'{active_dict["variables"][key][0][0]} or {active_dict["variables"][key][0][1]}'

            elif isinstance(active_dict["variables"][key][0], list):
                LOG.warning(f'{key}={active_dict["variables"][key][0]}')
                try:
                    random_items = random.sample(active_dict["variables"][key][0], 3)
                    LOG.debug(random_items)
                    return f'{random_items[0]}, {random_items[1]}, or {random_items[2]}'
                except ValueError:
                    return f'{active_dict["variables"][key][0][0]} or {active_dict["variables"][key][0][1]}'

            elif isinstance(active_dict["variables"][key][0], dict):
                LOG.debug(active_dict["variables"][key][0])
                LOG.debug(list(active_dict["variables"][key][0].keys()))
                try:
                    pick_short = []
                    keys_list = list(active_dict["variables"][key][0].keys())
                    random.shuffle(keys_list)
                    LOG.debug(keys_list)
                    # random.shuffle(list(active_dict["variables"][key].keys()))
                    # LOG.debug(list(active_dict["variables"][key].keys()))
                    for k in keys_list:
                        if k and len(k.split(' ')) <= 3:
                            pick_short.append(k)
                            if len(pick_short) == 3:
                                break
                    LOG.debug(pick_short)
                    if len(pick_short) > 0:
                        random_items = pick_short
                    else:
                        random_items = random.sample(list(active_dict["variables"][key][0].keys()), 3)
                    return f'{random_items[0]}, {random_items[1]}, or {random_items[2]}'
                except ValueError:
                    random_items = list(active_dict["variables"][key][0].keys())
                    return f'{random_items[0]} or {random_items[1]}'
        except Exception as e:
            LOG.error(e)
            return ""

    def _variable_closest(self, key, user, message=None):
        """
        Find the option in a list of options that is closest to the passed variable value, else return the passed value.
        :param key: user input, list of options
        :param user: nick on klat server, else "local"
        :return: closest matched value
        """
        LOG.debug(message)
        # LOG.debug(f"DM: {key}, {user}")
        key = key.replace(list(self.variable_functions.keys())[4], '')
        # LOG.debug(key)
        # LOG.debug(user)
        active_dict = self.active_conversations[user].get_current_conversation()

        # Parse out relevant variables
        variable_name, list_options_key = key.split(',')
        try:
            LOG.debug(f"find {variable_name} value in {list_options_key}")
            if isinstance(active_dict["variables"][list_options_key][0], dict):
                list_of_options = active_dict["variables"][list_options_key][0].keys()
                options_type = "dict"
            else:
                list_of_options = active_dict["variables"][list_options_key]
                options_type = "list"
            # LOG.info(list_options)
            # LOG.info(variable_name)
            LOG.debug(f'find {active_dict["variables"][variable_name][0]} in {list_of_options}')
            # LOG.info(active_dict["variables"][list_options])
            closest_match = difflib.get_close_matches(f'{active_dict["variables"][variable_name][0]} ',
                                                      list_of_options, cutoff=0.4)
            LOG.debug(closest_match)

            # If difflib returns nothing, look for any option containing our search term and return the first one
            # if not closest_match:
            #     closest_match = [x for x in active_dict["variables"][list_options].keys() if
            #                      active_dict["variables"][variable_name] in x.lower()]
            # LOG.debug(closest_match)

            # Check for a match, else return "none" to be handled
            if len(closest_match) > 0:
                LOG.debug(f"closest_match={closest_match}")
                if options_type == "dict":
                    return active_dict["variables"][list_options_key][0].get(closest_match[0])
                else:
                    return closest_match[0]
            else:
                return "none"
        except Exception as e:
            LOG.error(e)
            return "none"
            # return active_dict["variables"][variable_name]

    def _variable_profile(self, key, user, message=None):
        """
        Lookup a variable from user configuration
        :param key: "." delimited profile parameter (ie. units.time)
        :param user: user profile requested
        :return: yml value for requested key
        """

        # LOG.debug(f"DM: {key}, {user}")
        LOG.debug(key)
        LOG.debug(user)
        # requested = key.split("{")[1].split("}")[0]
        # LOG.debug(requested)
        if '.' in key:
            section, variable = key.split('.')
        else:
            LOG.warning(f"Invalid profile request: {key}")
            self._run_exit(user, "ERROR", message)
            return

        LOG.debug(f"Lookup {section}.{variable}")
        section = section.lower().strip()
        # TODO: Simplify this logic
        if section == "speech":
            result = get_user_prefs(message)["speech"].get(variable)
        elif section == "user":
            result = get_user_prefs(message)["user"].get(variable)
        elif section == "brands":
            result = get_user_prefs(message)["brands"].get(variable)
        elif section == "location":
            result = get_user_prefs(message)["location"].get(variable)
        elif section == "unit":
            result = get_user_prefs(message)["units"].get(variable)
        else:
            LOG.warning(f"{section} is not a valid preference!")
            result = None
        LOG.debug(result)
        return result

    def _variable_skill(self, key, user, message=None):
        """
        Execute a skill and get the returned dialog dictionary
        :param key: intent to execute, data key to extract
        :param user: user profile requested
        :return: yml value for requested key
        """
        active_dict = self.active_conversations[user].get_current_conversation()
        # TODO: Skip Mycroft compat for now
        LOG.info(f"ENTERING VARIABLE SKILL FOR {key}")
        # LOG.info(key)
        intent, data_key = key.split(",", 1)
        data_key = data_key.strip()
        intent = active_dict["variables"].get(intent, [clean_quotes(intent)])[0]
        LOG.info(f"{intent}|{data_key}")
        LOG.info(f"BUILDING MESSAGE")
        to_emit = build_message("skill_data", intent, message, active_dict["speaker_data"])
        # LOG.info(f"MESSAGE BUILT WITH {to_emit.data}")
        resp = self.bus.wait_for_response(to_emit, "skills:execute.response", timeout=60)
        LOG.info(f"VARIABLE SKILL RESPONSE IS {resp}")
        LOG.info(f"MESSAGE TYPE {resp.msg_type} | MESSAGE DATA {resp.data}")
        LOG.info(f'returning: {resp.data.get("meta", {}).get("data", {}).get(data_key)}')
        return resp.data.get("meta", {}).get("data", {}).get(data_key)

    def _substitute_variables(self, user, line, message, do_wildcards=False):
        """
        Fills any variables into a line to evaluate
        :param user: nick on klat server, else "local"
        :param line: parsed line text from formatted_script
        :param do_wildcards: Boolean if '*' should be replaced with named variables for substitution
        :return: line with all variables substituted
        """
        active_dict = self.active_conversations[user].get_current_conversation()
        line = line.strip()
        LOG.debug(f"_sub_vars: {line}")
        # Handle wildcard substitutions (may include trailing punctuation)
        if do_wildcards:
            LOG.debug(f"Do Wildcards for {line}")
            i = 1
            for word in line.split():
                if "*" in word:
                    replacement = word.replace('*', "{_wildcard_" + str(i) + '}', 1)
                    line = line.replace(word, replacement, 1)
                    i += 1
            line = f'"{line}"'
        # while "*" in line.split():
        #     line = line.replace(' * ', " \{_wildcard_" + str(i) + '\} ')
        #     i += 1

        tokens = [line]
        LOG.info(f"TOKENS FOR {line} are {tokens}")
        variables = active_dict["variables"]
        LOG.debug(f"len(variables)={len(variables)}")
        join_char = ""
        # TODO: Use parser_data for this? DM
        if not (line.startswith('"') and line.endswith('"')) and not (line.startswith("'") and line.endswith("'")):
            # This is a non-literal line, check for any variable functions
            tokens = []
            remainder = line
            join_char = " "
            # if remainder.endswith(':'):
            #     remainder = remainder[:-1]
            while " " in remainder:
                token, remainder = remainder.split(" ", 1)
                if "(" in token and ")" not in token:
                    to_add, remainder = remainder.split(")", 1)
                    token = f"{token}{to_add})"
                if (token in variables.keys() or token.split('(')[0] in self.variable_functions.keys()) \
                        and not token.startswith('{') and ('=' not in remainder or '==' in remainder):
                    token = '{' + token + '}'
                # elif token.startswith('{'):
                tokens.append(token)
            if (remainder in variables.keys() or remainder.split('(')[0] in self.variable_functions.keys()) \
                    and not remainder.startswith('{'):
                remainder = '{' + remainder + '}'
            tokens.append(remainder)

            LOG.info(f"Non-literal tokens {tokens}")
        elif '{' in line and '}' in line:  # or '(' in line and ')' in line:
            # This is a quoted string with variable substitution

            tokens = []
            remainder = line
            while "{" in remainder:
                parsed, remainder = remainder.split("{", 1)
                key, remainder = remainder.split("}", 1)
                tokens.append(parsed)
                tokens.append("{" + key + "}")
            tokens.append(remainder)
            LOG.info(f"Quoted string {tokens}")
        LOG.info(f"ITERATING OVER TOKENS {tokens}")
        # Iterate through words and look for a substitution
        for token in tokens:
            if token.startswith('{') and token.endswith('}'):
                var = token.lstrip('{').rstrip('}')
                LOG.debug(var)
                if any(x for x in self.variable_functions if x in var):  # Handle variable substitution
                    LOG.debug(var)
                    cmd, key = var.split("(", 1)
                    key = key.rstrip(")")
                    LOG.debug(cmd)
                    result = self.variable_functions[cmd](key, user, message)

                    LOG.debug(f"replacing {token} with {result} in {line}")
                    index = tokens.index(token)
                    tokens.remove(token)
                    tokens.insert(index, str(result))

                else:  # Handle simple substitution
                    LOG.info(f"HANDLE SIMPLE SUBSTITUTION FOR {var}")
                    LOG.debug(var)

                    # Get variable value
                    raw_val = [""]
                    # Check if this variable is defined with a value in this script
                    if '[' in var and ']' in var:
                        var_name = var.split('[')[0]
                    else:
                        var_name = var
                    LOG.info(f"VAR_NAME {var_name} | DEFINED VARIABLES {variables}")
                    if var_name in variables.keys() and variables[var_name]:
                        raw_val = variables[var_name]
                    # Check if this variable is defined in a script that called this script
                    elif "." in var_name:
                        raw_val = self.active_conversations[user].user_scope_variables.get(var_name)
                    else:
                        for script in active_dict["pending_scripts"]:
                            if var_name in script.get("variables", {}).keys():
                                raw_val = script["variables"][var_name]
                                break

                    # Get a specific index from our raw value
                    if '[' in var and ']' in var:
                        var, indices = var.split('[', 1)
                        idx = indices.split(']', 1)[0]  # Multiple indices could be handled in the remainder here
                        LOG.debug(f"get {var}[{idx}] in {raw_val}")
                        # Wildcard return all
                        if idx == '*':
                            val = ', '.join(raw_val)  # if raw_value is list, this turns val into str
                            # val = raw_val
                        # Get value at requested index
                        elif idx in range(0, len(raw_val)):
                            val = variables.get(var, [''])[idx]
                        # Catch index out of range and return the last value
                        else:
                            val = variables.get(var, [''])[0]
                        LOG.debug(val)
                    # Just get the value and check it is a list and has at least one value
                    else:
                        val = raw_val
                        LOG.debug(val)
                        if not isinstance(val, list):
                            val = [val]
                        if len(val) == 0:
                            if var not in variables:
                                active_dict = self.active_conversations[user].get_current_conversation()
                                line_num = active_dict["formatted_script"][
                                    active_dict["current_index"]]["line_number"]
                                self.speak_dialog("error_at_line",
                                                  {"error": "undeclared variable",
                                                            "line": line_num,
                                                            "detail": line,
                                                            "script": active_dict["script_filename"]})
                            val = ""
                        if isinstance(val[0], list):
                            LOG.error(f"val is list of lists: {val}")
                            val = val[0]

                    # If variable is a list (no index requested), use the first element
                    if isinstance(val, list):
                        if len(val) > 1 and message.data.get("cc_data", {}).get("return_list", False):
                            new_word = ",".join(variables.get(var))
                        else:
                            new_word = str(val[0]).strip().strip('"')
                    else:
                        LOG.debug(f"Value is string. {val}")
                        new_word = str(val).strip().strip('"')

                    # Cleanup quotes in strings and lists
                    new_word = new_word.lstrip('"').rstrip('"').replace('", "', ", ")

                    LOG.debug(f"replacing {token} with {new_word} in {line}")
                    index = tokens.index(token)
                    tokens.remove(token)
                    tokens.insert(index, new_word)

            line = join_char.join(tokens)
            LOG.debug(f"interim: {line}")
        LOG.debug(f">>>{line}")
        return line

    def _update_language(self, message, language):
        """
        Called at script start and end to use the language requested in the script and then revert to user setting
        :param message:
        :param language:
        :return:
        """
        time.sleep(0.5)
        payload = {'utterances': [f'speak to me in {language.lower()} only silent'],
                   'first_language': [language.lower().replace('male', '').replace('female', '')],
                   'silent': True,
                   'flac_filename': message.context.get("flac_filename", ""),
                   "nick_profiles": message.context.get("nick_profiles", {})
                   }
        LOG.debug(f">>>>> Incoming from CC! speak to me in {language.lower()} only silent")
        self.bus.emit(Message("recognizer_loop:utterance", payload))
        time.sleep(0.5)

    def _handle_timeout(self, message):
        """
        Notify user they have not responded and script will exit
        :param message: message associated with last valid response
        """
        user = get_message_user(message)
        active_dict = self.active_conversations[user].get_current_conversation()
        LOG.debug(message)

        # Check that user is actively running a script
        if active_dict["script_filename"]:
            if active_dict["timeout_action"]:
                if user in self.awaiting_input:
                    self.awaiting_input.remove(user)
                self._run_goto(user, active_dict["timeout_action"], message)
            else:
                self.speak_dialog("TimeoutExit", {"duration": active_dict["timeout"]}, message=message, private=True,
                                  speaker=active_dict["speaker_data"])
                self._run_exit(user, None, message)
        else:
            LOG.warning(f"{user} is not active.")

    # Utterance checking and handling
    def check_speak_event(self, message):
        """
        Called when any speak event (Neon output) is found on the messagebus.
        If the spoken utterance matches `speak_execute`, continue execution.
        :param message: messagebus message being evaluated
        """
        # LOG.debug(f"DM: check_speak: {message.data}")
        try:
            user = get_message_user(message)
            if user not in self.active_conversations.keys():
                pass
            else:
                active_dict = self.active_conversations[user].get_current_conversation()

                if message.context.get("cc_data", {}).get("request", None):
                    LOG.info(message.data)
                    LOG.info(f'checking {message.context["cc_data"].get("request", "")} ?= {active_dict["last_request"]}')
                    if active_dict["script_filename"] and \
                            message.context["cc_data"].get("signal_to_check", None):
                        LOG.debug("Active, about to check request")
                        # Check if this speak event is related to the last request
                        if message.context["cc_data"]["request"] == active_dict.get("last_request", "") and \
                                user not in self.awaiting_input:
                            LOG.debug("Neon response found. Continuing script.")
                            active_dict["last_request"] = ""
                            # timeout = time.time() + self.speak_timeout

                            # If this is a 'Neon speak' event, wait for the utterance to be spoken
                            LOG.info(f'Waiting for {message.context["cc_data"]["signal_to_check"]}')
                            # while self.is_speaking() and time.time() < timeout:
                            # while is_speaking():
                            #     time.sleep(1)
                            LOG.debug("Done waiting.")
                            # message.context["cc_data"]["signal_to_check"] = ""
                            # LOG.debug(f"DM: Continue Script Execution Call")
                            # self._continue_script_execution(message, user)
        except TypeError:
            pass

    def converse(self, message=None):
        user = get_message_user(message)
        utterances = message.data.get('utterances')
        if not message or not message.context or not utterances:
            return False

        if "stop" in str(utterances[0]).split():
            # TODO: Is this necessary, if so should be a voc_match for proper language support DM
            LOG.info(f'Stop request for {user}, pass: {utterances}')
            return False
        elif message.context.get("cc_data", {}).get("execute_from_script", False):
            LOG.info(f'Script execute for {user}, pass: {utterances}')
            return False
        elif user in self.active_conversations and \
                self.active_conversations[user].get_current_conversation()\
                        .get("script_filename"):
            LOG.info(f'Script input for {user} consume: {utterances}')
            consumed = self.check_if_script_response(message)
            LOG.info(f"consumed={consumed}")
            if consumed:
                # Reset the timeout event
                conversation_data = self.active_conversations[user].get_current_conversation()
                event_name = f"CC_{user}_conversation"
                LOG.info(f'handle event: {event_name} in {conversation_data["timeout"]}')
                if conversation_data["timeout"] > 0:
                    next_deadline = datetime.datetime.now(self.sys_tz) +\
                                    datetime.timedelta(seconds=conversation_data["timeout"])
                    self.cancel_scheduled_event(event_name)
                    self.schedule_event(self._handle_timeout, next_deadline,
                                        data={**message.data, **message.context}, name=event_name)
            # Return whether or not the script used the passed utterance
            return consumed
        else:
            LOG.info(f'No script for {user}, pass: {utterances}')
            return False

    def check_if_script_response(self, message):
        """
        Evaluates an incoming utterance and determines if it is directed at the active script
        :param message: message to evaluate
        """
        LOG.debug(f"check_if_script_response: {message.data}")
        user = get_message_user(message)

        if user not in self.active_conversations.keys():
            return False
        active_dict = self.active_conversations.get(user).get_current_conversation()
        LOG.debug(message.data)

        if active_dict["script_filename"]:
            utterance = message.data.get("utterances")[0]
            # LOG.debug(utterance)
            if str(utterance).strip().startswith("neon "):
                LOG.warning(f"Removing leading 'neon ' from {utterance}")
                utterance = str(utterance).strip().replace("neon ", "", 1)
            # LOG.debug(f'DM: clc: {active_dict["current_loop_conditional"]}')
            LOG.debug(f"utterance={utterance}")

            # Handle exiting loop or skill file
            if utterance.strip() == "exit":  # TODO: Voc Match DM
                LOG.debug("Request to exit loop")
                try:
                    LOG.debug(f'loops_dict={active_dict["loops_dict"]}')
                    # goto_line = None
                    goto_idx = None
                    goto_ind = active_dict["current_index"]
                    if user in self.awaiting_input:
                        self.awaiting_input.remove(user)

                    # Iterate through loops to find active loop
                    for loop in active_dict["loops_dict"]:
                        LOG.debug(loop)
                        start = active_dict["loops_dict"][loop]["start"]
                        end = active_dict["loops_dict"][loop]["end"]

                        # Go to the end of this active loop and break
                        if start < active_dict["current_index"] < end:
                            goto_line = end
                            i = 0
                            # Find the index of the line number where the loop ends and continue from the following line
                            for line in active_dict["formatted_script"]:
                                if line["line_number"] == goto_line:
                                    LOG.debug(f'Found loop end at {i}: {line}')
                                    goto_idx = i + 1
                                    goto_ind = line["indent"]
                                    break
                                i += 1
                            break

                    # We have a loop end to goto
                    if goto_idx:
                        active_dict["current_index"] = goto_idx
                        active_dict["last_indent"] = goto_ind
                        self.bus.emit(message.reply("skill.converse.response",
                                                    {"skill_id": "custom-conversation.neon", "result": True}))
                        # time.sleep(1)
                        LOG.debug(f"about to continue from {goto_idx}")
                        # LOG.debug(f"DM: Continue Script Execution Call")
                        self._continue_script_execution(message, user)
                    # There is no active loop, just exit the whole thing
                    else:
                        LOG.debug("Exit called by user request")
                        self.runtime_execution["exit"](user, "exit", message)
                except Exception as e:
                    LOG.error(e)
                    self.runtime_execution["exit"](user, "exit", message)
                return True
            # Handle variable assignment  TODO: This not working?
            elif user in self.awaiting_input:
                self.awaiting_input.remove(user)
                LOG.debug(f"Remove {user} from awaiting_input")
                LOG.debug(f'variables={active_dict["variables"]}')
                LOG.debug(f'variable_to_fill={active_dict["variable_to_fill"]}')
                assigned_value = None

                # If variable value is currently a list, selection must be in that list to be assigned
                if ',' in active_dict["variable_to_fill"]:
                    var_to_fill, list_to_check = active_dict["variable_to_fill"].split(',', 1)
                    LOG.debug('select from list!')
                    LOG.debug(active_dict["variables"][list_to_check])
                    for opt in active_dict["variables"][list_to_check]:
                        if opt in utterance:
                            assigned_value = opt
                            break
                else:
                    assigned_value = utterance

                # If we have a valid value to assign to the variable
                if assigned_value:
                    to_update = active_dict["variable_to_fill"]

                    # Push new value to front of list
                    if isinstance(active_dict["variables"][to_update], list):
                        LOG.debug("insert")
                        active_dict["variables"][to_update].insert(0, assigned_value.strip())
                    elif active_dict["variables"][to_update]:
                        LOG.debug("add to string")
                        active_dict["variables"][to_update] = [assigned_value.strip(), to_update]
                    else:
                        LOG.debug("initialize")
                        active_dict["variables"][to_update] = [assigned_value.strip()]

                    LOG.debug(f'variables[{to_update}] = {active_dict["variables"][to_update]}')

                    # active_dict["audio_responses"][active_dict["variable_to_fill"]] = \
                    #     message.data["cc_data"].get("audio_file", None)
                    if message.context.get("audio_file", None):
                        to_update = active_dict["variable_to_fill"]
                        assigned_value = message.context["audio_file"]
                        if assigned_value.endswith(".flac"):
                            # The actual user audio is the extensionless file, mp3 is response
                            assigned_value = assigned_value.rstrip(".flac")

                        # Example Filename
                        # {transcriptsDir}/{user}-2020-07-07/{user}-2020-07-07 20:33:37.034829 {utterance} .wav'

                        # Push new audio file value to front of list
                        if isinstance(active_dict["audio_responses"].get(to_update), list) and assigned_value:
                            active_dict["audio_responses"][to_update].insert(0, assigned_value.strip())
                        elif active_dict["audio_responses"].get(to_update) and assigned_value:
                            active_dict["audio_responses"][to_update] = [assigned_value.strip(), to_update]
                        else:
                            active_dict["audio_responses"][to_update] = [assigned_value.strip()]

                    # assigned_value = active_dict["variable_to_fill"].lower()
                    # LOG.info(assigned_value)
                    LOG.debug(f'>>> {active_dict["variables"]}')
                    LOG.debug(f'>>> {active_dict["audio_responses"]}')
                    self.bus.emit(message.reply("skill.converse.response",
                                                {"skill_id": "custom-conversation.neon", "result": True}))
                    time.sleep(1)
                    # LOG.debug(f"DM: Continue Script Execution Call")
                    self._continue_script_execution(message, user)
                    return True
                else:
                    self.awaiting_input.append(user)
                    LOG.debug(f"{user} awaiting input")
                    # self.create_signal(f"{user}_CC_inputNeeded")
                    # LOG.debug(f"DM: Created {user}_CC_inputNeeded")

                    return False
            # Else, consume the utterance
            else:
                LOG.warning("utterance consumed, not as input?")
                return True
        else:
            return False

    def _handle_script_upload(self, message):
        """
        Handles emit from server module when a script is uploaded. Notifies the uploading user of upload status.
        :param message: Message associated with upload status
        """
        name = message.data.get("script_name")
        author = message.data.get("script_author")
        status = message.data.get("script_status")
        LOG.info(f"Script {name} upload by {author} | status={status}")
        LOG.debug(f"message.data={message.data}")

        if status == "exists":
            self.speak_dialog("upload_failed", {"name": name, "reason": "the filename already exists"}, message=message)
        elif status in ("created", "updated"):
            self.speak_dialog("upload_success", {"name": name, "state": status}, message=message)
            # Update config to track last updated time
            # self.ngi_settings.update_yaml_file("updates", message.data.get("file_basename"), time.time(), final=True)
        # elif status == "updated":
        #     self.speak_dialog("upload_success", {"name": name, "state": status}, message=message)
        elif status == "no title":
            self.speak_dialog("upload_failed", {"name": name, "reason": "no script title was found"}, message=message)

    def stop(self):
        pass

    def update_transcript(self, utterance, filename, start_time):
        """
        Called to save user-neon conversation while a script is running
        :param utterance: conversation line to be saved
        :param filename: filename of a running script
        :param start_time: time when script is considered to start running
        """
        with open(os.path.join(self.transcript_location, f'{filename}_{start_time}.txt'), 'a') as transcript:
            transcript.write(utterance)

    # Helper functions
    # def _add_syn_intent(self, message):
    #     """
    #     Creates a global synonym and adds it to user configuration
    #     :param message: message object with key/value pair
    #     """
    #     LOG.debug(f"DM: add synonym intent: {message.data}")
    #     # user = "local"
    #     # if self.server:
    #     #     user = nick(message.data["flac_filename"])
    #     # if user in self.active_conversations.keys():
    #     #     LOG.debug(self.active_conversations[user])
    #     # else:
    #     #     self._reset_values(user)
    #     speech_dict = self.preference_speech(message)
    #     existing, new_synonym = '', ''
    #     LOG.info(message.data)
    #     try:
    #         new_synonym = (message.data.get('new'))
    #         if not new_synonym:
    #             if not message.data.get("new_from_cc") and isinstance(message.data.get('utterances', ""), list):
    #
    #                 LOG.debug(message.data)
    #                 to_parse = message.data.get('utterances')[0]
    #                 LOG.debug(to_parse)
    #                 pattern = re.compile(r'(make|set|add)\s+(?P<new>.*)\sas (a|\s)+synonym\s+(to|for)\s+'
    #                                      r'(?P<existing>.*)').finditer(to_parse)
    #                 for i in pattern:
    #                     new_synonym = (i.group('new')).rstrip()
    #                     existing = (i.group('existing')).rstrip()
    #                 LOG.debug(new_synonym)
    #                 LOG.debug(existing)
    #                 if not new_synonym or not existing:
    #                     pattern = re.compile(r'(make|set|add)\s+(?P<new>.*)a(s a|s|\s)*\s+synonym\s+(to|for)\s+'
    #                                          r'(?P<existing>.*)').finditer(to_parse)
    #                     for i in pattern:
    #                         new_synonym = (i.group('new')).rstrip()
    #                         existing = (i.group('existing')).rstrip()
    #                     LOG.debug(new_synonym)
    #                     LOG.debug(existing)
    #                 if not new_synonym or not existing:
    #                     LOG.debug('Invalid request')
    #                     return
    #             else:
    #                 new_synonym = message.data.get("new_from_cc")
    #                 existing = message.data.get("existing")
    #                 LOG.debug(new_synonym)
    #                 LOG.debug(existing)
    #                 if isinstance(new_synonym, list):
    #                     try:
    #                         # LOG.debug("Here")
    #                         if new_synonym != speech_dict['synonyms'][existing]:
    #                             new_synonym.extend(speech_dict['synonyms'][existing])
    #                             # LOG.debug("Here")
    #                         else:
    #                             return
    #                     except KeyError as e:
    #                         LOG.warning(e)
    #                     to_add = {**speech_dict['synonyms'], **{existing: new_synonym}}
    #                     if self.server:
    #                         user_dict = self.build_user_dict(message)
    #                         user_dict["speech"]["synonyms"] = to_add
    #                         self.socket_io_emit(event="update profile", kind="skill",
    #                                             flac_filename=message.context["flac_filename"], message=user_dict)
    #                     else:
    #                         self.user_config.update_yaml_file(header='speech', sub_header='synonyms', value=to_add)
    #                         self.bus.emit(Message('check.yml.updates'),
    #                                       {"modified": ["ngi_user_info"]}, {"origin": "custom-conversation.neon"})
    #
    #         else:
    #             existing = message.data.get('existing')
    #         if new_synonym != existing:
    #             if new_synonym in speech_dict['synonyms'].keys():
    #                 # LOG.debug("speak new another key?")
    #                 self.speak_dialog('new_is_another_key', {'new': new_synonym.title()})
    #                 return
    #             if new_synonym in speech_dict['synonyms'].values():
    #                 # LOG.debug("speak new another value")
    #                 self.speak_dialog('new_is_another_value',
    #                                   {'new': new_synonym.title(),
    #                                    'existing': [x for x, y in speech_dict['synonyms'].
    #                                                 items() if new_synonym in y][0]})
    #                 return
    #             if existing not in speech_dict['synonyms'].keys():
    #                 # LOG.debug("New Existing")
    #                 self.speak_dialog("new_existing", {'new': new_synonym,
    #                                                    'existing': existing})
    #                 if not isinstance(new_synonym, list):
    #                     new_synonym = [new_synonym]
    #             else:
    #                 LOG.debug("DM: ??")
    #                 if new_synonym in speech_dict['synonyms'][existing]:
    #                     self.speak_dialog('already_exists', {'new': new_synonym.title(),
    #                                                          'existing': existing})
    #                     return
    #
    #                 self.speak_dialog("already_filled",
    #                                   {'new': new_synonym,
    #                                    'already_filled':
    #                                        ", ".join(speech_dict['synonyms'][existing]),
    #                                    'existing': existing})
    #                 LOG.debug(new_synonym)
    #                 LOG.debug(speech_dict['synonyms'][existing])
    #                 if not isinstance(new_synonym, list):
    #                     new_synonym = [new_synonym]
    #                 new_synonym.extend(speech_dict['synonyms'][existing])
    #                 LOG.debug(new_synonym)
    #                 LOG.debug(speech_dict['synonyms'][existing])
    #             if not new_synonym and not existing:
    #                 raise TypeError
    #
    #             to_add = {**speech_dict['synonyms'], **{existing: new_synonym}}
    #             self.user_config.update_yaml_file(header='speech', sub_header='synonyms', value=to_add)
    #             self.bus.emit(Message('check.yml.updates',
    #                                   {"modified": ["ngi_user_info"]}, {"origin": "custom-conversation.neon"}))
    #         else:
    #             self.speak_dialog('same_values', {'new': new_synonym.title(),
    #                                               'existing': existing})
    #     except TypeError as e:
    #         LOG.error(f'Error adding {new_synonym} to {existing}')
    #         LOG.error(e)
    #         return

    ######################################################################
    # def check_end(self, message):
    #     """
    #     Called when any Neon speak event is finished.
    #     Clears the current speak signal and sets `current` to False
    #     :param message: messagebus message being evaluated
    #     """
    #     # LOG.debug(f"DM: check_end: {message.data}")
    #     user = "local"
    #     if self.server:
    #         LOG.warning("DM: check_end called on server!")
    #         user = nick(message.data["flac_filename"])
    #         LOG.debug(f"{user}")
    #     if user not in self.active_conversations.keys():
    #         self._reset_values(user)
    #     active_dict = self.active_conversations[user]
    #     # if self.check_for_signal(f"{user}_CC_active", -1):
    #     #     LOG.info("CC: In end speech")
    #     #     LOG.info(active_dict["current"])
    #     #     if active_dict["current"]:
    #     #         LOG.info(active_dict["speak_execute_flac"])
    #     #         self.check_for_signal(active_dict["speak_execute_flac"])
    #     #         active_dict["current"] = False

    # if self.check_for_signal(f"{user}_CC_choosingValue"):
    #     if utterance not in active_dict["variables"][active_dict["selection_required"]]:
    #         # self.speak()
    #         self.create_signal(f"{user}_CC_choosingValue")
    #         return
    #     active_dict["selection_made"] = utterance
    #     LOG.info(utterance)
    #     utterance = active_dict["selection_required"].lower()

    # if active_dict["outer_option"] == 0 or active_dict["outer_option"] == '0':
    #     try:
    #         LOG.info(active_dict["script_dict"])
    #         base_intents_num = len(list(active_dict["script_dict"].values())[0])
    #         options = {i: i.lower().split(" ", 1)[1].split(" or ") for i in
    #                    list(active_dict["script_dict"].keys()) if i.split(" ", 1)[0].split(".")[1] == '1'}
    #         LOG.info(options)
    #         if not active_dict["variables"] and base_intents_num != len(options):
    #             self.speak_dialog("ProblemInFile", {"file_name": active_dict["script_filename"]})
    #             self.stop()
    #             return
    #         LOG.info(utterance)
    #
    #         found_response = [key for key, value in list(options.items()) if utterance in value]
    #         LOG.debug(f"DM: {found_response}")
    #         if not found_response:
    #             return
    #         active_dict["outer_option"] = found_response[0].split('.', 1)[0]
    #         active_dict["indentation"] = int(found_response[0].split('.', 1)[1].split('.', 1)[0]) + 1
    #         LOG.info((active_dict["script_dict"][found_response[0]]))
    #         if active_dict["loops_dict"]:
    #             LOG.info(f'{active_dict["outer_option"]}.'
    #                      f'{int(found_response[0].split(".", 1)[1].split(".", 1)[0])}')
    #             LOG.info(list(active_dict["loops_dict"].items()))
    #
    #             # Iterate over all loops
    #             for loop, conditionals in list(active_dict["loops_dict"].items()):
    #                 LOG.debug(f'DM: loop={loop}, conditionals={conditionals}, '
    #                           f'compare with: {active_dict["outer_option"]}.'
    #                           f'{int(found_response[0].split(".", 1)[1].split(".", 1)[0])}')
    #
    #                 # If current execution is the start of the loop
    #                 if f'{active_dict["outer_option"]}.' \
    #                    f'{int(found_response[0].split(".", 1)[1].split(".", 1)[0])}' == conditionals[0]:
    #                     LOG.info(conditionals[0])
    #                     LOG.info(loop)
    #                     active_dict["current_loop"] = loop
    #                     LOG.info(active_dict["current_loop"])
    #
    #                     # Update current loop values
    #                     try:
    #                         active_dict["current_loop_conditional"] = [conditionals[2]]
    #                         try:
    #                             active_dict["current_loop_conditional"].append(conditionals[3])
    #                             LOG.debug(f'DM: clc={active_dict["current_loop_conditional"]}')
    #                             # self.create_signal(f"{user}_CC_untilConditionalLoop")
    #                             active_dict["until_conditional_loop"] = True
    #                         except IndexError as e:
    #                             LOG.info(e)
    #                             # self.create_signal(f"{user}_CC_untilConditionalLoopUtterance")
    #                             active_dict["until_conditional_utterance"] = True
    #                     except IndexError as e:
    #                         LOG.info(e)
    #         LOG.info(f'current_loop_conditional={active_dict["current_loop_conditional"]}')
    #         # self._non_variable_speak_execute(found_response, message) if not active_dict["variables"] \
    #         #     else self._execute_as_utterance(found_response, message)
    #         LOG.debug(f"DM: about to execute: found_response={found_response}")
    #         self._execute_as_utterance(found_response, message)
    #     except IndexError as e:
    #         LOG.info(e)
    #
    # else:
    #     LOG.info(active_dict["outer_option"])
    #     LOG.info(active_dict["indentation"])
    #     LOG.debug(f'DM: loops_dict={active_dict["loops_dict"]}')
    #     # if active_dict["loops_dict"]:
    #     #     self._check_loops(user)
    #     LOG.info(f' option.indent={active_dict["outer_option"]}.{active_dict["indentation"]}')
    #     formatted_index = f'{active_dict["outer_option"]}.{active_dict["indentation"]}.'
    #     # LOG.info(utterance)
    #     options = {i: i.lower().split(" ", 1)[1].split(" or ") for i in
    #                list(active_dict["script_dict"].keys()) if i.split(" ", 1)[0] == formatted_index}
    #     # LOG.info(options)
    #     # LOG.info(options)
    #     # LOG.info(options)
    #     found_response = [key for key, value in list(options.items()) if utterance in value]
    #     try:
    #         print(found_response[0])
    #         print(active_dict["script_dict"][found_response[0]])
    #         active_dict["outer_option"] = found_response[0].split('.', 1)[0]
    #         active_dict["indentation"] = int(found_response[0].split('.', 1)[1].split('.', 1)[0]) + 1
    #         # LOG.info(f'{self.counter}.{self.inner_option}.')
    #         # LOG.info(list(self.to_say.keys()))
    #         # LOG.info(f'{self.counter}.{self.inner_option}.' in list(self.to_say.keys()))
    #         # LOG.info(any("2.3. " in x for x in list(self.to_say.keys())))
    #         if not any(f'{active_dict["outer_option"]}.{active_dict["indentation"]}.' in x
    #                    for x in list(active_dict["script_dict"].keys())):
    #             LOG.info("not in the list, end of cases")
    #             LOG.info(active_dict["current_loop"])
    #             try:
    #                 if not active_dict["current_loop"]:
    #                     LOG.info(list(active_dict["loops_dict"].items()))
    #                     LOG.info(f'{active_dict["outer_option"]}.{active_dict["indentation"]}')
    #                     for loop, conditionals in list(active_dict["loops_dict"].items()):
    #                         LOG.info(conditionals[1])
    #                         LOG.info(f'{active_dict["outer_option"]}.{int(active_dict["indentation"])}')
    #                         LOG.info(f'{active_dict["outer_option"]}.{int(active_dict["indentation"])}' ==
    #                         conditionals[1])
    #                         if f'{active_dict["outer_option"]}.{int(active_dict["indentation"])}' ==
    #                         conditionals[1]:
    #                             LOG.info(conditionals[0])
    #                             LOG.info(loop)
    #                             active_dict["current_loop"] = loop
    #                             if conditionals[0] != '0':
    #                                 active_dict["outer_option"] = conditionals[0].split(".")[0]
    #                                 active_dict["indentation"] = conditionals[0].split(".")[1]
    #                             else:
    #                                 active_dict["outer_option"] = conditionals[0]
    #                                 active_dict["indentation"] = conditionals[0]
    #                             LOG.info(f'{active_dict["outer_option"]}.'
    #                                      f'{active_dict["indentation"]}')
    #                 else:
    #                     conditionals = active_dict["loops_dict"][active_dict["current_loop"]]
    #                     # LOG.info(self.variables[v[2]])
    #                     # LOG.info(v[3])
    #                     # LOG.info(self.current_loop_conditional[1])
    #                     # if not self.check_for_signal(f"{user}_CC_untilConditionalLoop", -1) \
    #                     #     or (self.check_for_signal(f"{user}_CC_untilConditionalLoop", -1) and
    #                     #         not active_dict["variables"][conditionals[2]][0] == conditionals[3] ==
    #                     #         active_dict["current_loop_conditional"][1]):
    #                     if not active_dict["until_conditional_loop"] \
    #                             or (active_dict["until_conditional_loop"] and
    #                                 not active_dict["variables"][conditionals[2]][0] == conditionals[3] ==
    #                                     active_dict["current_loop_conditional"][1]):
    #                         LOG.info(conditionals)
    #                         if conditionals[0] != '0':
    #                             active_dict["outer_option"] = conditionals[0].split(".")[0]
    #                             active_dict["indentation"] = conditionals[0].split(".")[1]
    #                         else:
    #                             active_dict["outer_option"] = conditionals[0]
    #                             active_dict["indentation"] = conditionals[0]
    #
    #                     else:
    #                         LOG.info("at the cond == var")
    #                         # self._non_variable_speak_execute(found_response, message) if not \
    #                         #     active_dict["variables"] \
    #                         #     else self._execute_as_utterance(found_response, message)
    #                         to_send = []
    #                         for loop, conditionals in list(active_dict["loops_dict"].items()):
    #                             to_send.append(float(conditionals[0]))
    #                         new_loop_index = find_closest(to_send, active_dict[
    #                             "loops_dict"][active_dict["current_loop"]][0])
    #                         LOG.info(new_loop_index)
    #                         LOG.info(
    #                             ".1" in f'{new_loop_index}' and ".1" in active_dict[
    #                                 "loops_dict"][active_dict["current_loop"]][0])
    #                         LOG.info(active_dict["loops_dict"][active_dict["current_loop"]][0])
    #                         LOG.info("0" in list(active_dict["loops_dict"].values()))
    #                         LOG.info(active_dict["loops_dict"].values())
    #                         if (".1" in f'{new_loop_index}' and ".1" in active_dict[
    #                             "loops_dict"][active_dict["current_loop"]][0]) or \
    #                                 f'{new_loop_index}' == "0.0":
    #                             if "0" in list(active_dict["loops_dict"].values())[0]:
    #                                 active_dict["outer_option"] = 0
    #
    #                                 # self.speak_init_message(message)
    #                                 return
    #                             else:
    #                                 LOG.info("DM: Exiting ('0' is first in loops_dict")
    #
    #                                 self.speak_dialog("Exiting",
    #                                                   {"file_name":
    #                                                    re.sub("_", " ", active_dict["script_filename"])
    #                                                    })
    #                                 # self.text_command_options = ''
    #                                 self.check_for_signal(f"{user}_CC_active")
    #                                 self._reset_values()
    #                                 self.bus.emit(Message("mycroft.stop"))
    #                                 return
    #                         else:
    #                             active_dict["outer_option"] = f'{new_loop_index}'.split(".")[0]
    #                             active_dict["indentation"] = f'{new_loop_index}'.split(".")[1]
    #                             # self._check_loops(user)
    #
    #             except Exception as e:
    #                 LOG.info(e)
    #             # if f'{self.counter}.{self.counter_2}.' in self.loop_counter:
    #             # LOG.info(self.loop_counter.values().index(f'{self.counter}.{self.counter_2}.'))
    #             # self.counter_2 -= 1
    #     except IndexError:
    #         pass
    #     # self._non_variable_speak_execute(found_response, message) if not active_dict["variables"] \
    #     #     else self._execute_as_utterance(found_response, message)
    #     if not self.check_for_signal(f'{user}_CC_exiting'):
    #         if active_dict["outer_option"] == '0' or active_dict["outer_option"] == 0:
    #             LOG.info(utterance)
    #             # self.speak_init_message(message)
    #         index = f'{active_dict["outer_option"]}.{active_dict["indentation"]}'
    #         if index == "0.0":
    #             index = '0'
    #         if (not active_dict["current_loop"] and not
    #             self.check_for_signal(f"{user}_CC_active", -1)) or \
    #                 (not any(f'{index}.'
    #                          in x for x in list(active_dict["script_dict"].keys()))):
    #             LOG.info(f'DM: {user} exiting no current_loop and not active OR '
    #                      f'no {active_dict["outer_option"]}.{active_dict["indentation"]}. in '
    #                      f'{list(active_dict["script_dict"].keys())}')
    #
    #             self.speak_dialog("Exiting", {"file_name": re.sub("_", " ", active_dict["script_filename"])})
    #             self.check_for_signal(f"{user}_CC_active")
    #             self._reset_values()
    #             self.bus.emit(Message("mycroft.stop"))
    #             return

    # def _non_variable_speak_execute(self, found_response, message_from_check):
    #     """
    #     DEPRECIATED. Everything now goes to _execute_as_utterance
    #     :param found_response:
    #     :param message_from_check:
    #     :return:
    #     """
    #     LOG.warning(f">>>>>DM: non_variable_speak_execute called!!!<<<<<")
    #     user = "local"
    #     if self.server:
    #         user = nick(message_from_check.data["flac_filename"])
    #     if user not in self.active_conversations.keys():
    #         self._reset_values(user)
    #     active_dict = self.active_conversations[user]
    #     try:
    #         while self.check_for_signal(f"{user}_CC_active", -1):
    #             # if not isinstance(self.to_say[found_response[0]][0], list):
    #             for i in active_dict["script_dict"][found_response[0]]:
    #                 # LOG.debug(f"DM: about to execute something")
    #                 if ".python: " in i:
    #                     exec(i.split(" ", 1)[1])
    #                     continue
    #                 if '.execute: ' in i:
    #                     LOG.info([i.split(" ", 1)[1]])
    #                     to_execute = i.split(" ", 1)[1]
    #                     LOG.info(to_execute)
    #                     # LOG.debug(f"DM: {to_execute}")
    #                     if to_execute != 'exit':
    #                         payload = {
    #                             'utterances': [to_execute],
    #                             'flac_filename': message_from_check.data.get('flac_filename', ''),
    #                             'mobile': message_from_check.data.get('mobile', False),
    #                             'nick_profiles': message_from_check.data.get('nick_profiles', {}),
    #                             'cc_data': {'speak_execute': to_execute
    #                                         # 'counter': self.counter,
    #                                         # 'counter2': self.active_conversations[user]["counter_2"],
    #                                         # 'cc_input_needed': False,
    #                                         # 'cc_choosing_value': False,
    #                                         # 'current_loop_conditional': [''],
    #                                         # 'current_loop': ''
    #                                         }
    #                         }
    #                         # self.emitter.emit()
    #                         LOG.info(i)
    #                         LOG.debug(f">>>>> Incoming from CC! {to_execute}")
    #                         self.create_signal("CORE_neonInUtterance")
    #                         self.bus.emit(Message("recognizer_loop:utterance", payload))
    #                     else:
    #                         self.create_signal(f'{user}_CC_exiting')
    #                         message_from_check.data["utterances"] = [to_execute]
    #                         # LOG.debug("DM: _non_variable_speak_execute")
    #                         self.check_if_script_response(message_from_check)
    #                         return
    #                 else:
    #                     self.speak(i.split(" ", 1)[1],
    #                                message=Message("speak",
    #                                                {"flac_filename": message_from_check.data.get('flac_filename', ''),
    #                                                 'mobile': message_from_check.data.get('mobile', False),
    #                                                 'nick_profiles': message_from_check.data.get('nick_profiles', {}),
    #                                                 'cc_data': {'speak_execute': i.split(" ", 1)[1]
    #                                                             # 'counter': self.counter,
    #                                                             # 'counter2': self.counter_2,
    #                                                             # 'cc_input_needed': False,
    #                                                             # 'cc_choosing_value': False,
    #                                                             # 'current_loop_conditional': [''],
    #                                                             # 'current_loop': ''
    #                                                             }
    #                                                 }))
    #
    #                 # if device != "server":
    #                 active_dict["speak_execute_flac"] = i.split(" ", 1)[1]
    #                 self.create_signal(active_dict["speak_execute_flac"])
    #                 timeout = 0
    #                 while self.check_for_signal(active_dict["speak_execute_flac"], -1) and \
    #                         timeout < TIMEOUT and self.check_for_signal(f"{user}_CC_active", -1):
    #                     # LOG.info("waiting")
    #                     time.sleep(1)
    #                     timeout += 1
    #                     # LOG.info(timeout)
    #                 if timeout < TIMEOUT:
    #                     time.sleep(1)
    #                 else:
    #                     self.check_for_signal(active_dict["speak_execute_flac"])
    #             #         self.speak(i.split(" ", 1)[1], message=
    #             #                 Message("speak", {"flac_filename": message_from_check.data.get('flac_filename', ''),
    #             #                                   'cc_data': {'speak_execute': i.split(" ", 1)[1],
    #             #                                                'counter': self.counter,
    #             #                                                'counter2': self.counter_2,
    #             #                                                'cc_input_needed': False,
    #             #                                                'cc_choosing_value': False,
    #             #                                                'current_loop_conditional': [''],
    #             #                                                'current_loop': ''}}))
    #             #         if device == 'server':
    #             #             time.sleep(0.1)
    #             # else:
    #             #     for i in self.to_say[found_response[0]][0]:
    #             #         self.speak(i.split(" ", 1)[1],  message=
    #             #                 Message("speak", {"flac_filename": message_from_check.data.get('flac_filename', ''),
    #             #                                   'cc_data': {'speak_execute': i.split(" ", 1)[1],
    #             #                                                'counter': self.counter,
    #             #                                                'counter2': self.counter_2,
    #             #                                                'cc_input_needed': False,
    #             #                                                'cc_choosing_value': False,
    #             #                                                'current_loop_conditional': [''],
    #             #                                                'current_loop': ''}}))
    #             #         if device == 'server':
    #             #             time.sleep(0.1)
    #             #     for i in self.to_say[found_response[0]][1]:
    #             #         LOG.info([i.split(" ", 1)[1]])
    #             #         payload = {
    #             #             'utterances': [i.split(" ", 1)[1]],
    #             #             'flac_filename': message_from_check.data.get('flac_filename', ''),
    #             #             'cc_data': {'speak_execute': i.split(" ", 1)[1],
    #             #                                    'counter': self.counter,
    #             #                                    'counter2': self.counter_2,
    #             #                                    'cc_input_needed': False,
    #             #                                    'cc_choosing_value': False,
    #             #                                    'current_loop_conditional': [''],
    #             #                                    'current_loop': ''}}
    #             #         # self.emitter.emit()
    #             #         self.bus.emit(Message("recognizer_loop:utterance", payload))
    #             #         if device != "server":
    #             #             self.speak_execute_flac = i.split(" ", 1)[1]
    #             #             self.create_signal(self.speak_execute_flac)
    #             #             timeout = 0
    #             #             while self.check_for_signal(self.speak_execute_flac, -1) and timeout < TIMEOUT and \
    #             #                     self.check_for_signal("CC_Active", -1):
    #             #                 # LOG.info("waiting")
    #             #                 time.sleep(.5)
    #             #                 timeout += .5
    #             #                 # LOG.info(timeout)
    #             #             self.check_for_signal(self.speak_execute_flac)
    #             break
    #     except IndexError:
    #         pass
    #
    # def _execute_as_utterance(self, found_response, message_from_check):
    #     """
    #     Executes a speak or execute line after evaluating any variables.
    #     Creates and emits a messagebus event and waits
    #     for the corresponding speak or skill response.
    #     :param found_response: String to evaluate
    #     :param message_from_check: Associated Message object (server use)
    #     :return: None
    #     """
    #     # LOG.debug(f"DM: _variable_speak_execute({found_response}, {message_from_check.data}")
    #     user = "local"
    #     if self.server:
    #         user = nick(message_from_check.data["flac_filename"])
    #     if user not in self.active_conversations.keys():
    #         self._reset_values(user)
    #     active_dict = self.active_conversations[user]
    #     LOG.info(found_response)
    #     try:
    #         while self.check_for_signal(f"{user}_CC_active", -1):
    #             # if not isinstance(self.to_say[found_response[0]][0], list):
    #             for i in active_dict["script_dict"][found_response[0]]:
    #                 if ".python: " in i:
    #                     exec(i.split(" ", 1)[1])
    #                     continue
    #                 final_result = ''
    #                 to_say = i.split(" ", 1)[1]
    #                 try:
    #                     # LOG.info(to_say)
    #                     final_result = []
    #                     for x in to_say.split(" "):
    #                         # LOG.info(final_result)
    #                         # LOG.info(x)
    #                         if "{" in x:
    #                             custom_function = [y for y in self.variable_functions if y in x]
    #                             LOG.info(custom_function)
    #                             if not custom_function:
    #                                 final_result.append(active_dict["variables"][x[1:-1]][0])
    #                                 # LOG.info(final_result)
    #                             else:
    #                                 final_result.append(self.variable_functions[custom_function[0]](x, user))
    #                         else:
    #                             final_result.append(x)
    #                         # LOG.info(final_result)
    #                 except Exception as e:
    #                     LOG.info(e)
    #                 # LOG.info(final_result)
    #                 final_result = " ".join(final_result)
    #                 LOG.info(final_result)
    #                 # LOG.debug(f'DM: {active_dict["script_dict"]}')
    #                 # print(to_say_formatted)
    #                 if '.execute: ' not in i:
    #                     LOG.debug(message_from_check.data)
    #                     self.speak(final_result, self.check_for_signal(f"{user}_CC_inputNeeded", -1),
    #                                message=Message("speak",
    #                                                {'flac_filename': message_from_check.data.get('flac_filename', ''),
    #                                                 'mobile': message_from_check.data.get('mobile', False),
    #                                                 'nick_profiles': message_from_check.data.get("nick_profiles", {}),
    #                                                 'cc_data': {'speak_execute': final_result}
    #                                                 #             'counter': self.counter,
    #                                                 #             'counter2': self.counter_2,
    #                                                 #             'cc_input_needed': False,
    #                                                 #             'cc_choosing_value': False,
    #                                                 #             'current_loop_conditional': [''],
    #                                                 #             'current_loop': ''}
    #                                                 }))
    #
    #                 else:
    #                     if final_result != "exit":
    #                         payload = {
    #                             'utterances': [final_result],
    #                             'flac_filename': message_from_check.data.get('flac_filename', ''),
    #                             'mobile': message_from_check.data.get('mobile', False),
    #                             'nick_profiles': message_from_check.data.get('nick_profiles', {}),
    #                             'cc_data': {'speak_execute': final_result}
    #                             #             'counter': self.counter,
    #                             #             'counter2': self.counter_2,
    #                             #             'cc_input_needed': False,
    #                             #             'cc_choosing_value': False,
    #                             #             'current_loop_conditional': [''],
    #                             #             'current_loop': ''}
    #                         }
    #                         # self.emitter.emit()
    #                         self.create_signal("CORE_neonInUtterance")
    #                         LOG.debug(f">>>>> Incoming from CC! {final_result}")
    #                         self.bus.emit(Message("recognizer_loop:utterance", payload))
    #                     else:
    #                         self.create_signal(f'{user}_CC_exiting')
    #                         message_from_check.data["utterances"] = [final_result]
    #                         # LOG.debug("DM: _variable_speak_execute")
    #                         self.check_if_script_response(message_from_check)
    #                         return
    #                     # if device != 'server':
    #                 self.check_for_signal(active_dict["speak_execute_flac"])
    #                 active_dict["speak_execute_flac"] = final_result
    #                 LOG.info(f'creating signal: {active_dict["speak_execute_flac"]}')
    #                 self.create_signal(active_dict["speak_execute_flac"])
    #                 timeout = 0
    #                 while self.check_for_signal(active_dict["speak_execute_flac"], -1) and timeout < TIMEOUT and \
    #                         self.check_for_signal(f"{user}_CC_active", -1):
    #                     LOG.info(f'waiting for {active_dict["speak_execute_flac"]}')
    #                     time.sleep(.5)
    #                     timeout += .5
    #                     # LOG.info(timeout)
    #                 self.check_for_signal(active_dict["speak_execute_flac"])
    #             break
    #     except IndexError:
    #         pass
    #
    # def _check_loops(self, user):
    #     """
    #     Called during script execution. Checks active loops against current script position
    #     :param user:
    #     :return:
    #     """
    #     LOG.debug(f"DM: {user}")
    #     if user not in self.active_conversations.keys():
    #         self._reset_values(user)
    #     active_dict = self.active_conversations[user]
    #     LOG.debug(f"DM: loops_dict={active_dict['loops_dict']}")
    #
    #     # Iterate over active loops and corresponding indices
    #     # for loop, counters in active_dict["loops_dict"].items():
    #     #     LOG.debug(f'DM: option.indent={active_dict["outer_option"]}.{active_dict["indentation"]}')
    #     #     LOG.debug(f"DM: counters={counters}")
    #     #     # Check if we are at the start of a new loop
    #     #     if f'{active_dict["outer_option"]}.{active_dict["indentation"]}' == counters[0]:
    #     #         LOG.info(f"DM: v0={counters[0]}")
    #     #         LOG.info(f"DM: loop={loop}")
    #     #         active_dict["current_loop"] = loop
    #     #         LOG.info(active_dict["current_loop"])
    #     #
    #     #         try:
    #     #             active_dict["current_loop_conditional"] = [counters[1]]
    #     #             try:
    #     #                 active_dict["current_loop_conditional"].append(counters[2])
    #     #                 # self.create_signal(f"{user}_CC_untilConditionalLoop")
    #     #                 active_dict["until_conditional_loop"] = True
    #     #             except IndexError as e:
    #     #                 LOG.info(e)
    #     #                 # self.create_signal(f"{user}_CC_untilConditionalLoopUtterance")
    #     #                 active_dict["until_conditional_utterance"] = True
    #     #         except IndexError as e:
    #     #             LOG.info(e)
    #     #         LOG.info(f'DM: {active_dict["current_loop_conditional"]}')

    # Handle messagebus events

    # def loop_checks(self, new_loop_index, message_from_check):
    #     user = "local"
    #     LOG.debug(f"DM: loop_checks({new_loop_index}, {message_from_check.data}")
    #     if self.server:
    #         user = nick(message_from_check.data["flac_filename"])
    #     if user not in self.active_conversations.keys():
    #         self._reset_values(user)
    #     active_dict = self.active_conversations[user]
    #     LOG.info(f"DM: new_loop_index: {new_loop_index}")
    #     LOG.info(f"DM: loops_dict: {active_dict['loops_dict']}")
    #     # if (".1" in f'{new_loop_index}' and ".1" in active_dict["loops_dict"][active_dict["current_loop"]][0]) or \
    #     #         f'{new_loop_index}' == "0.0":
    #     #     if "0" in list(active_dict["loops_dict"].values())[0] and not \
    #     #             self.check_for_signal(f"{user}_CC_exited_top_loop"):
    #     #         self.create_signal(f"{user}_CC_exited_top_loop")
    #     #         active_dict["outer_option"] = 0
    #     #
    #     #         self.speak_init_message(message_from_check)
    #     #         return
    #     #     else:
    #     #         LOG.info("DM: Exiting '0' not in loops_dict[0] and signal exists")
    #     #
    #     #         self.speak_dialog("Exiting", {"file_name": re.sub("_", " ", active_dict["formatted_file"])})
    #     #         # self.text_command_options = ''
    #     #         self.check_for_signal(f"{user}_CC_active")
    #     #         self._reset_values()
    #     #         self.bus.emit(Message("mycroft.stop"))
    #     #         return
    #     # else:
    #     #     active_dict["outer_option"] = f'{new_loop_index}'.split(".")[0]
    #     #     active_dict["indentation"] = f'{new_loop_index}'.split(".")[1]
    #     #     for k, v in list(active_dict["loops_dict"].items()):
    #     #         if f'{active_dict["outer_option"]}.{active_dict["indentation"]}' == v[0]:
    #     #             LOG.info(v[0])
    #     #             LOG.info(k)
    #     #             active_dict["current_loop"] = k
    #     #             LOG.info(active_dict["current_loop"])
    #     #             try:
    #     #                 active_dict["current_loop_conditional"] = [v[2]]
    #     #                 try:
    #     #                     active_dict["current_loop_conditional"].append(v[3])
    #     #                     # self.create_signal(f"{user}_CC_untilConditionalLoop")
    #     #                     active_dict["until_conditional_loop"] = True
    #     #                 except IndexError as e:
    #     #                     LOG.info(e)
    #     #                     # self.create_signal(f"{user}_CC_untilConditionalLoopUtterance")
    #     #                     active_dict["until_conditional_utterance"] = True
    #     #             except IndexError as e:
    #     #                 LOG.info(e)
    #     #             LOG.info(f'{active_dict["current_loop_conditional"]}')
    #     #             return

    # def speak_init_message(self, message):
    #     """
    #     Depreciated? Speak whatever is in to_say. Called at script start and during execution
    #     :param message: Message from handle_start_script intent match
    #     """
    #     LOG.debug(message.data)
    #     user = "local"
    #     if self.server:
    #         user = nick(message.data["flac_filename"])
    #     if user not in self.active_conversations.keys():
    #         self._reset_values(user)
    #     active_dict = self.active_conversations[user]
    #     LOG.debug(f">>>START: {active_dict}")
    #     try:
    #         # If no variables, just speak whatever is in to_say
    #         if not active_dict["variables"]:
    #             for i in list(active_dict["script_dict"].values())[0]:
    #                 LOG.info(str(i).split(" ", 1)[1])
    #                 self.speak(str(i).split(" ", 1)[1])
    #         # Handle anything with variables
    #         else:
    #             LOG.info(list(active_dict["script_dict"].keys())[0])
    #             message.data["utterances"] = ['tmp']
    #             self._execute_as_utterance([list(active_dict["script_dict"].keys())[0]], message)
    #     except IndexError as e:
    #         LOG.error(e)

# # Parse Script options at preload/start of script
#     def _parse_header_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of header lines
#         (i.e. could be used to get title, description, etc.)
#         :param user: nick on klat server, else "local"
#         :param line_data: dict of data associated with current line being parsed
#         """
#         LOG.debug(line_data)
#         active_dict = self.active_conversations[user]
#         option = line_data["command"]
#         value = line_data["text"].strip()
#         LOG.info(f"DM: option={option} | value={value}")
#         if option == "timeout":
#             if " " in value:
#                 timeout, action = value.split(" ", 1)
#                 LOG.info(f"DM: {timeout}")
#                 active_dict["timeout"] = int(timeout)
#                 active_dict["timeout_action"] = action.strip().strip('"')
#             else:
#                 LOG.info(f"DM: {value}")
#                 value = int(value)
#                 active_dict["timeout"] = value
#                 active_dict["timeout_action"] = None
#             LOG.debug(f"DM: {active_dict}")
#
#     def _parse_goto_option(self, user, line_data=None):
#         """
#         Finds tag lines and indexes them for use at runtime
#         :param user: nick on klat server, else "local"
#         """
#         LOG.debug(line_data)
#         active_dict = self.active_conversations[user]
#         line_txt = str(line_data["text"]).strip()
#         tag = None
#         if line_txt.startswith('@'):
#             tag = line_txt[1:]
#             # line_num = line_data["line_number"]
#             # active_dict["goto_tags"][tag] = line_num
#         elif line_txt.lower().startswith("tag:"):
#             tag = line_txt.split(':')[1].strip()
#             # line_num = line_data["line_number"]
#             # active_dict["goto_tags"][tag] = line_num
#
#         line_num = line_data["line_number"]
#         if tag and tag in active_dict["goto_tags"]:
#             LOG.error(f"duplicate tag! {line_data}")
#             self.speak_dialog("error_at_line", {"error": "duplicate tag",
#                                                 "line": line_num,
#                                                 "detail": line_data,
#                                                 "script": active_dict["sript_filename"].replace('_', ' ')})
#
#         active_dict["goto_tags"][tag] = line_num
#
#     def _parse_language_option(self, user, line_data=None):
#         """
#         Sets speaker_data parameter at script load time (doesn't change language here)
#         :param user: nick on klat server, else "local"
#         """
#         LOG.debug(line_data)
#         # LOG.debug(f"DM: {user}")
#         if user not in self.active_conversations.keys():
#             self._reset_values(user)
#         active_dict = self.active_conversations[user]
#
#         # Only handle the first Language line; ignore subsequent ones inside the script
#         if not active_dict["speaker_data"].get("name", None):
#             line = re.sub('"', '', str(line_data["text"])).split()
#             LOG.debug(line)
#             if "male" in line:
#                 line.remove("male")
#                 gender = "male"
#             elif "female" in line:
#                 line.remove("female")
#                 gender = "female"
#             else:
#                 LOG.warning("No gender specified in Language line!")
#                 try:
#                     gender = self.preference_speech(Message("nick_for_profile", context={"nick": user}))["tts_gender"]
#                     LOG.debug(f"Got user preferred gender: {gender}")
#                 except Exception as e:
#                     LOG.error(e)
#                     gender = "female"
#
#             LOG.debug(line)
#             language = line[0].lower()
#             if language in self.configuration_available["ttsVoice"]:
#                 voice = self.configuration_available["ttsVoice"][language][gender]
#                 LOG.debug(voice)
#
#                 active_dict["speaker_data"] = {"name": "Neon",
#                                                "language": language,
#                                                "gender": gender,
#                                                "voice": voice,
#                                                "override_user": True}
#             else:
#                 LOG.error(f"{language} is not a valid language option!")
#             # active_dict["speaker_data"] = \
#             #     active_dict["line"].lower().rstrip().split('"')[1].translate({ord(c): None for c in '!@#$?"'})
#
#     def _parse_clap_option(self, user, line_data=None):
#         """
#         Modifies yml to add specified number of claps to alias running this skill file at script load time
#         :param user: nick on klat server, else "local"
#         """
#         LOG.debug(line_data)
#         # LOG.debug(f"DM: {user}")
#         if user not in self.active_conversations.keys():
#             self._reset_values(user)
#         active_dict = self.active_conversations[user]
#         try:
#             LOG.debug(active_dict["line"] + "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
#             num = int(active_dict["line"].split(" ")[1])
#             LOG.debug(num)
#             self.user_info_available["clap_sets"]["cc"][num] = \
#                 f'run my {active_dict["script_filename"]} skill file'
#             self.create_signal("CLAP_cc")
#             LOG.debug(self.user_info_available["clap_sets"]["cc"])
#             self.user_config.update_yaml_file(header="clap_sets", sub_header="cc",
#                                               value=self.user_info_available["clap_sets"]["cc"])
#             self.bus.emit(Message('check.yml.updates',
#                                   {"modified": ["ngi_user_info"]}, {"origin": "custom-conversation.neon"}))
#         except Exception as e:
#             LOG.error(e)
#             default = {1: '', 2: '', 3: '', 4: ''}
#             self.user_config.update_yaml_file(header="clap_sets", sub_header="cc", value=default)
#
#     def _parse_python_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of python lines (i.e. could be used to validate code)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_case_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of case lines (could be used to check conditional is defined)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_if_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of if lines (i.e. could be used to check conditional is defined)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_else_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of else lines (i.e. could be used to check for preceding if)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_execute_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of execute lines (i.e. could be used to validate skill intents)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_speak_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of speak lines
#         (i.e. could check for invalid characters or variable substitutions, names speaking)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_substitute_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of substitution lines
#         (i.e. could check for invalid variable pairs)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_variable_option(self, user, line_data=None):
#         """
#         Loads variable names and default values into `variables` at script load time
#         :param user: nick on klat server, else "local"
#         """
#         LOG.debug(line_data)
#         # LOG.debug(f"DM: {user}")
#         if user not in self.active_conversations.keys():
#             self._reset_values(user)
#         active_dict = self.active_conversations[user]
#         # if f'{list(self.pre_parser_options.keys())[3].title()}:' \
#         #         not in active_dict["line"] and \
#         #         f'{list(self.pre_parser_options.keys())[1].title()}:' not in active_dict["line"]:
#
#         # Parse out variable name (key)
#         remainder = None
#         value = None
#         if ':' in line_data["text"] and "{" in line_data["text"].split(':')[0] and \
#                 "}" in line_data["text"].split(':')[0]:  # Handle Variable: {name}: value  This syntax is depreciated
#             key = line_data["text"].rstrip().split('{')[1].split("}")[0]
#             line_data["text"] = line_data["text"].replace("{"+key+"}", key)
#             # key = active_dict["line"].rstrip().split('{')[1].split("}")[0]
#         elif "=" in line_data["text"]:  # Handle Variable: name = value
#             key, value = line_data["text"].split('=', 1)
#             if "{" in key:  # Variable: {name} = value
#                 key = key.split('{', 1)[1].split('}', 1)[0]
#             elif ":" in key:  # Variable: name = value
#                 key = key.split(':', 1)[1].strip()
#             else:  # Catch surrounding quotes and whitespace
#                 key = key.strip('"').strip()
#             value = value.strip(" ").strip('"').replace('", "', ",").replace(", ", ",").split(",")
#         elif len(line_data["text"].strip().split(" ", 1)) == 2:  # Handle Variable: name: value/Variable: name = value
#             LOG.debug(line_data["text"].strip().split(" ", 1))
#             key, remainder = line_data["text"].replace(':', '').strip().split(" ", 1)
#         else:  # Handle Variable: name
#             LOG.debug(line_data["text"])
#             key = line_data["text"].replace(':', '').strip()
#             remainder = None
#
#         if "{" in key or "}" in key:
#             key = key.split('{')[1].split('}')[0]
#         LOG.debug(f"key={key}")
#         active_dict["last_variable"] = key
#
#         # Parse variable init value
#         if "}:" in line_data["text"]:  # This syntax is depreciated
#             value = [x.strip() for x in line_data["text"].rstrip().split("}:")[1].split(',')]
#             # value = [x.strip() for x in active_dict["line"].rstrip().split("}:")[1].split(',')]
#         elif remainder:  # This Syntax is depreciated
#             LOG.debug(remainder)
#             if "=" in remainder:  # Handle Variable: Name = Value
#                 value = [x.strip() for x in line_data["text"].rstrip().split('=', 1)[1].split(',')]
#             elif ":" in remainder:  # Handle Variable: Name: Value  This syntax is depreciated
#                 value = [x.strip() for x in line_data["text"].rstrip().split(':', 1)[1].split(',')]
#             else:  # Handle "Variable: Name" or "Variable: Name Value"
#                 value = [x.strip() for x in line_data["text"].rstrip().split(',')]
#         elif not value:
#             # value = None
#             LOG.warning(f"variable {key} initialized without a value!")
#         LOG.debug(value)
#
#         # Check if function is called in variable assignment
#         if value:
#             # LOG.debug(self.variable_functions)
#             # for opt in self.variable_functions:
#             #     # LOG.debug(f"looking for {opt} in {value[0]}")
#             #
#             #     # If we find an option, process it and stop looking for more options
#             #     if opt in value[0]:
#             #         # LOG.debug(f"found {opt} in {value[0]}")
#             #         if '{' in str(value[0]):
#             #             val = str(value[0]).split('{')[1].split('}')[0]
#             #         elif '(' in str(value[0]):
#             #             val = str(value[0]).split('(')[1].split(')')[0]
#             #         else:
#             #             val = value
#             #         value = self.variable_functions[opt](val, user, None)
#             #         # LOG.debug(type(value))
#             #         if isinstance(value, str):
#             #             if ',' in value:
#             #                 value = value.split(',')[1]
#             #             else:
#             #                 value = [value]
#             #         # LOG.debug(value)
#             #
#             #         # LOG.debug(type(value))
#             #         if isinstance(value, list):
#             #             if not [i for i in value if ':' in i]:
#             #                 # Standard list of values
#             #                 LOG.debug(active_dict["variables"])
#             #                 active_dict["variables"][key] = value
#             #                 LOG.debug(active_dict["variables"])
#             #             else:
#             #                 # list of key/value pairs, parse to dict
#             #                 LOG.debug(active_dict["variables"])
#             #                 active_dict["variables"][key] = \
#             #                     {i.split(": ")[0]: i.split(": ")[1] for i in value}
#             #                 LOG.debug(active_dict["variables"])
#             #         elif isinstance(value, dict):
#             #             # Dict
#             #             LOG.debug(active_dict["variables"])
#             #             active_dict["variables"][key] = value
#             #             LOG.debug(active_dict["variables"])
#             #         else:
#             #             # String/Int, parse to list
#             #             LOG.debug(active_dict["variables"])
#             #             active_dict["variables"][key] = [value]
#             #             LOG.debug(active_dict["variables"])
#             #         break
#
#             LOG.debug(f"After parsing opts: {key} = {value}")
#
#         # This is a literal value, just parse it in
#         if key not in active_dict["variables"].keys():
#             LOG.debug("No function called in variable assignment")
#
#             # Try parsing string into list, excluding substitution variables
#             if any(x for x in self.variable_functions if value.startswith(x)):
#                 LOG.debug(f"value is a function: {value}")
#             elif isinstance(value, str) and "," in value and not value.strip().endswith(','):
#                 value = value.split(",")
#                 # LOG.debug(value)
#                 for i in range(0, len(value)):
#                     # LOG.debug(value[i])
#                     value[i] = value[i].strip()
#                     # LOG.debug(value[i])
#                 # LOG.debug(value)
#             elif isinstance(value, list) and len(value) == 1 and value[0] in ("''", '""'):
#                 LOG.debug(f"{key} is an empty list")
#                 value = []
#             LOG.info(f"adding variable: {key} = {value}")
#             active_dict["variables"][key] = value
#         # self.variables.append(self.line.rstrip().split(': ')[1].\
#         #     translate({ord(c): None for c in '!@#$?"'}).split(", "))
#
#     def _parse_loop_option(self, user, line_data=None):
#         """
#         Parses loops into `loops_dict` at script load time
#         :param user: nick on klat server, else "local"
#         """
#         # LOG.debug(f"DM: {user}")
#         if user not in self.active_conversations.keys():
#             self._reset_values(user)
#         active_dict = self.active_conversations[user]
#         # LOG.debug(f'active_dict: {active_dict}')
#         # LOG.debug(f'line_data: {line_data}')
#         # LOG.debug(f"DM: loops_dict={active_dict['loops_dict']}")
#         # LOG.debug(f"DM: line_index={active_dict['line_index']}")
#         # if not active_dict["in_speak"] and f'{list(self.pre_parser_options.keys())[3].title()}:' \
#         #         not in active_dict["line"] \
#         #         and f'{list(self.pre_parser_options.keys())[1].title()}:' not in active_dict["line"]:  # Case
#         if str(active_dict["line"]).lstrip().startswith("LOOP "):
#             loop_parts = re.sub("\n", "", str(active_dict["line"]).lstrip()).split(' ')
#             LOG.debug(loop_parts)
#             loop_name = loop_parts[1]
#             line_num = line_data.get("line_number", -1)
#
#             # Create loop dict if not exists
#             if loop_name not in active_dict["loops_dict"]:
#                 LOG.debug(f"Adding {loop_name} to loops_dict")
#                 active_dict["loops_dict"][loop_name] = dict()
#
#             # This is a loop end with no conditional
#             if "END" in loop_parts:
#                 LOG.debug(f"Loop END line {line_num}")
#                 active_dict["loops_dict"][loop_name]["end"] = line_num
#
#             # This is a conditional loop end
#             elif "UNTIL" in loop_parts:
#                 LOG.debug(f"Loop UNTIL line {line_num}")
#                 active_dict["loops_dict"][loop_name]["end"] = line_num
#                 LOG.debug(f"loop_parts: {loop_parts}")
#                 variable = loop_parts[3]
#                 if len(loop_parts) > 4:
#                     value = loop_parts[5]
#                 else:
#                     value = "True"
#                 LOG.debug(f"Loop variable={variable}")
#                 LOG.debug(f"Loop value={value}")
#                 active_dict["loops_dict"][loop_name]["end_variable"] = variable
#                 active_dict["loops_dict"][loop_name]["end_value"] = value
#
#             # This is the beginning of a loop
#             else:
#                 # active_dict["loops_dict"][loop_name] = dict()
#                 LOG.debug(f'start loop {loop_name} at {line_num}')
#                 active_dict["loops_dict"][loop_name]["start"] = line_num
#                 # active_dict["loops_dict"][active_dict["line"].lower().replace("loop", '').strip()] = \
#                 #     [active_dict["line_index"]]
#             LOG.debug(f'loops_dict={active_dict["loops_dict"]}')
#
#     def _parse_synonym_option(self, user, line_data=None):
#         """
#         Loads synonyms and emits to add them to YML configuration at script load time
#         :param user: nick on klat server, else "local"
#         """
#         # LOG.debug(f"DM: {user}")
#         LOG.debug(line_data)
#         if user not in self.active_conversations.keys():
#             self._reset_values(user)
#         active_dict = self.active_conversations[user]
#         LOG.debug(active_dict["line"])
#         # Parse invalid characters from synonym string
#         synonyms = active_dict["line"].lower().split(': ')[1].translate({ord(c): None for c in '!@#$"'})\
#             .rstrip().replace(", ", ",")
#         # Parse list of synonyms
#         synonyms = synonyms.split(',') if ',' in synonyms else [synonyms]
#
#         active_dict["synonym_command"] = f'run my {re.sub("_", " ", active_dict["script_filename"])} skill file'
#         # LOG.debug(synonyms)
#         active_dict["synonyms"].extend(synonyms)
#         # LOG.debug(active_dict["synonyms"])
#         # payload = {
#         #     'cmd_phrase': f'run my {re.sub("_", " ", active_dict["script_filename"])} skill file',
#         #     'cc_synonyms': synonyms
#         # }
#         #
#         # self.bus.emit(Message("SS_new_syn", payload, {"origin": "custom-conversation.neon",
#         #                                               "nick": user}))
#
#     def _parse_exit_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of exit lines (i.e. could check for unreachable code, etc.)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_set_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of set lines (i.e. could add to variables, etc.)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_run_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of run lines (i.e. could validate script exists, etc.)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_reconvey_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of reconvey lines (i.e. could add placeholder variables, etc.)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_input_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of voice_input lines (could add placeholder variables, etc.)
#         :param user: nick on klat server, else "local"
#         """
#         pass
#
#     def _parse_email_option(self, user, line_data=None):
#         """
#         Does any pre-execution parsing and validation of email lines (i.e. could check for subject, body, etc.)
#         :param user: nick on klat server, else "local"
#         """
#         pass

# _load_to_cache
# timer_start = time.time()
# try:
#     while self.check_for_signal("CC_updating", -1) and time.time() - timer_start < 10:
#         time.sleep(0.5)
#         LOG.debug("updating conversation scripts from server...")
#     self.check_for_signal("CC_updating")
#     LOG.debug(f"About to open {active_dict['script_filename']}")
#
#     # Open file
#     with open(os.path.join(self.__location__,
#                            "script_txt/" + active_dict["script_filename"] + ".txt"),
#               'r', encoding='utf-8') as script_file:
#
#         # Notify start of script if not for cache only
#         if not preload_only:
#             self.speak_dialog("Starting", {"file_to_run": file_to_run})
#             LOG.debug(f' Time to speak {time.time() - timer_start}')
#
#         # Remove existing synonyms
#         yml_key = f'run my {re.sub("_", " ", active_dict["script_filename"])} skill file'
#         LOG.debug(f"remove: {yml_key}")
#         synonyms = self.user_info_available["speech"]["synonyms"]
#         # LOG.debug(f"{synonyms}")
#         if yml_key in dict(synonyms).keys():
#             LOG.debug(f">>>>>removing {yml_key}")
#             synonyms.pop(yml_key)
#         LOG.debug(f"{synonyms}")
#         self.user_config.update_yaml_file("speech", "synonyms", synonyms, multiple=False, final=True)
#
#         # Loop through each line of the script_file
#         line_num = 0
#         in_comment_block = False
#         for active_dict["line"] in script_file:
#             # LOG.debug(active_dict["line"])
#
#             # Parse line_number and text into line_data dict
#             line_num += 1
#             line_data = dict()
#             last_line = dict()
#             if len(active_dict["formatted_script"]) > 0:
#                 last_line = active_dict["formatted_script"][-1]
#                 # LOG.debug(f"last_line: {last_line}")
#             line_data["line_number"] = line_num
#             text_content = str(active_dict["line"]).strip()
#             # LOG.debug(text_content)
#             if ': ' in text_content:
#                 # Parse out command from text
#                 # LOG.debug(f"stripping ':' from {text_content}")
#                 text_content = text_content.split(': ', 1)[1]
#             # text_content = text_content.lstrip('"').rstrip('"')
#             line_data["text"] = text_content.lstrip('.').lstrip()
#
#             # Parse out comment lines
#             if active_dict["line"].lstrip().startswith('"""') or active_dict["line"].lstrip().endswith('"""'):
#                 if in_comment_block:
#                     in_comment_block = False
#                 else:
#                     in_comment_block = True
#             if active_dict["line"].lstrip().lstrip('.').startswith("#") or in_comment_block:
#                 # LOG.info(f'Got comment - {active_dict["line"]}')
#                 continue
#             if active_dict["line"].strip() == "":
#                 # LOG.info(f'Got empty line - {active_dict["line"]}')
#                 continue
#
#             # Parse indent level (count of 4-space indents, rounding down)
#             if active_dict["line"].startswith("."):
#                 num_leading = len(active_dict["line"]) - len(active_dict["line"].lstrip('.'))
#             else:
#                 active_dict["line"] = active_dict["line"].replace("\t", "    ")
#                 num_leading = len(active_dict["line"]) - len(active_dict["line"].lstrip())
#             indent = int((num_leading - (num_leading % 4)) / 4)
#
#             # Speak warning if indentation is incorrect
#             if num_leading % 4 != 0:
#                 LOG.warning(f'indent error at {line_num} in {file_to_run}')
#                 if not preload_only:
#                     self.speak_dialog("error_at_line", {"error": "line indent",
#                                                         "line": line_num,
#                                                         "detail": active_dict["line"],
#                                                         "script": file_to_run.
#                                       replace('_', ' ')})
#
#                     # self.speak(f"Indent error found at line number {line_num}")
#
#             # LOG.debug(f"DM: leading={num_leading}, indent={indent}")
#             line_data["indent"] = indent
#
#             # Check for case statements
#             parent_cases = None
#             # If indent decreased and we have an active case, check if we've exited that case
#             if line_data["indent"] < last_line.get("indent", 0) and \
#                     len(last_line["parent_case_indents"]) > 0 and \
#                     line_data["indent"] != last_line["parent_case_indents"][-1] + 1:
#                 LOG.debug(f"Outdented line")
#                 # LOG.debug(f"About to pop parent_case (maybe)")
#                 parent_cases = deepcopy(last_line["parent_case_indents"][0:-1])
#                 # LOG.debug(f'cases: {parent_cases}')
#
#             # Catch case condition
#             elif last_line.get("parent_case_indents", None) and \
#                     line_data["indent"] == last_line["parent_case_indents"][-1] + 1:
#                 line_data["command"] = "case"
#
#             # Loop through and find any options in the line
#             for option in self.pre_parser_options:
#                 try:
#                     # LOG.info(f"looking for option: {option}")
#                     # If the line declares an option, go parse it into our active_dict and update our line_data
#                     line_txt = active_dict["line"].lower().lstrip('.').strip()
#                     if line_txt.startswith(option) and \
#                             (':' in line_txt or line_txt.startswith('@')            # @ tag
#                              or not line_txt.replace(option, "").strip() or         # option only
#                              option == "loop" and "LOOP" in active_dict["line"] or  # loop definition
#                              line_txt.replace(option, "").startswith("(") or        # function
#                              line_txt.replace(option, "").startswith("{")):         # function (depreciated)
#                         # LOG.debug(f"Explicit option: {active_dict['line'].lower()}")
#                         line_data["command"] = option
#                         try:
#                             self.pre_parser_options[option](user, line_data)
#                         except Exception as x:
#                             LOG.error(x)
#                         continue
#
#                 except Exception as e:
#                     LOG.error(e)
#                     LOG.error(active_dict["line"])
#                     LOG.error(option)
#                     LOG.error(user)
#                     LOG.error(line_data)
#
#             try:
#                 # Check for cases in variable_functions
#                 if not line_data.get("command", None):
#                     for option in self.variable_functions:
#                         if active_dict["line"].lower().lstrip().startswith(option):
#                             line_data["command"] = option
#                     # LOG.debug(f'DM: command from variable_functions: {line_data.get("command", "ERROR")}')
#                 # Check if this is a parent-case option
#                 if not line_data.get("command", None):
#                     if parent_cases:
#                         for indent in parent_cases:
#                             if line_data["indent"] == indent + 1:
#                                 line_data["command"] = "case"
#                                 LOG.debug("This is a case option")
#
#                 # If no command in-lined and not a case, copy command from last line
#                 if not line_data.get("command", None):
#                     # Check for variable assignment
#                     if "=" in line_data["text"] and \
#                             line_data["text"].split("=", 1)[0].strip() in active_dict["variables"]:
#                         line_data["command"] = "set"
#                     # Same or greater indentation as last line, inherit that command unless disallowed
#                     elif line_data["indent"] >= last_line["indent"] \
#                             and last_line["command"] not in self.no_implicit_multiline:
#                         line_data["command"] = last_line["command"]
#                         if line_data["command"] == "variable" and active_dict["last_variable"]:
#                             var_to_update = active_dict["last_variable"]
#                             LOG.debug(var_to_update)
#                             LOG.debug(active_dict["variables"][var_to_update])
#
#                             # Append to variable (write if empty)
#                             if line_data["text"].rstrip(","):
#                                 if active_dict["variables"][var_to_update]:
#                                     active_dict["variables"][var_to_update]\
#                                         .append(line_data["text"].rstrip(","))
#                                 else:
#                                     active_dict["variables"][var_to_update] = [line_data["text"]]
#                             else:
#                                 LOG.warning(f"null value line: {line_data}")
#                             LOG.debug(active_dict["variables"][var_to_update])
#                     # Invalid assignment, outdented from previous
#                     else:
#                         LOG.error(f"No explicit command, try assuming set: {line_data}")
#                         if "=" in line_data["text"]:
#                             line_data["command"] = "set"
#                         else:
#                             LOG.error(f"No command found for: {line_data}")
#                             # Speak error if script launched , skip for preload
#                             if not preload_only:
#                                 self.speak_dialog("error_at_line", {"error": "null command",
#                                                                     "line": line_data["line_number"],
#                                                                     "detail": line_data["text"],
#                                                                     "script": active_dict["script_filename"]})
#
#                             # if line_data["indent"] < last_line["indent"]:
#                     #     LOG.warning(f'Line indentation error at line: {line_data}')
#
#                 # If we previously found parent_cases, write them out
#                 if parent_cases:
#                     LOG.debug(f"parent_cases {parent_cases}")
#                     line_data["parent_case_indents"] = parent_cases
#                 # If this line is a case statement, add it to the list
#                 else:
#                     line_data["parent_case_indents"] = deepcopy(last_line.get("parent_case_indents", []))
#                     if line_data["command"] == "case" and \
#                             active_dict["line"].lower().lstrip().startswith("case"):
#                         LOG.debug(f'append {indent} to cases')
#                         line_data["parent_case_indents"].append(indent)
#
#                 # Do any pre-cache static parsing
#                 if line_data["command"] == "@":
#                     line_data["command"] = "tag"
#                 # Write out line data
#                 LOG.debug(f'write out line_data: {line_data}')
#                 active_dict["formatted_script"].append(line_data)
#             except Exception as e:
#                 LOG.error(e)
#     # End Line loop
#
#     # Log data from parsing
#     try:
#         # LOG.info(pprint(active_dict["script_dict"]))
#         LOG.debug(f' Time to parse the file {time.time() - timer_start}')
#         LOG.debug(f' Selected language is {active_dict["speaker_data"]}')
#         LOG.debug(f' Variables are {active_dict["variables"]}')
#         LOG.debug(f' Loops requested are {active_dict["loops_dict"]}')
#         LOG.debug(f' Timeout is {active_dict["timeout"]} | {active_dict["timeout_action"]}')
#         LOG.debug(f' Synonyms are: {active_dict["synonyms"]}')
#         LOG.debug(f'>>>>> formatted: {active_dict["formatted_script"]}')
#
#         # if active_dict["variables"] == {}:
#         #     LOG.debug("Empty variables! put something there")
#         #     active_dict["variables"] = {'': ['']}
#         # Old scheme timings:
#         #     0.0009930133819580078 with dict and no string
#         #     0.0016369819641113281 with dict
#         #     0.0026772022247314453 with if/else
#     except Exception as e:
#         LOG.error(e)
# except FileNotFoundError as e:
#     LOG.debug(e)
#     self.speak_dialog("NotFound", {"file_to_open": active_dict["script_filename"].replace('_', ' ')})
#     self._reset_values()
#     return
