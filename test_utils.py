# NEON AI (TM) SOFTWARE, Software Development Kit & Application Development System
#
# Copyright 2008-2020 Neongecko.com Inc. | All Rights Reserved
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
# US Patents 2008-2020: US7424516, US20140161250, US20140177813, US8638908, US8068604, US8553852, US10530923, US10530924
# China Patent: CN102017585  -  Europe Patent: EU2156652  -  Patents Pending

import unittest

from utils_emulate import Conversation, ConversationManager


class TestConversation(unittest.TestCase):

    def setUp(self) -> None:
        self.script_meta = {"foo": "bar"}
        self.script_filename = "foo"
        self.conversation = Conversation(script_meta=self.script_meta, script_filename=self.script_filename)

    def test_getitem(self):
        self.assertEqual(self.conversation["script_meta"], self.conversation.script_meta)

    def test_setitem(self):
        self.conversation["line"] = "random"
        self.assertEqual(self.conversation.line, "random")

    def test_contains(self):
        self.assertTrue("script_meta" in self.conversation)
        self.assertFalse("random" in self.conversation)

    def test_len(self):
        conversation_length = len(self.conversation)
        self.assertIsInstance(conversation_length, int)
        self.conversation.foo = "bar"
        self.assertEqual(len(self.conversation), conversation_length+1)

    def test_setitem_protected(self):
        with self.assertRaises(AttributeError):
            self.conversation["_script_meta"] = "foo"

    def test_setitem_protected_with_for_items_loop(self):
        with self.assertRaises(AttributeError):
            for a, b in self.conversation.items():
                if a.startswith("_"):
                    self.conversation[a] = "foo "

    def test_protected_property(self):
        self.assertEqual(self.conversation["script_meta"], {"foo": "bar"})

        self.conversation._script_meta = {"foobar": "baz"}
        self.assertEqual(self.conversation["_script_meta"], {"foobar": "baz"})
        with self.assertRaises(AttributeError):
            self.conversation["script_meta"] = {"foo": "bar"}

    def test_items(self):
        self.assertIsInstance(self.conversation.items(), type({}.items()))
        self.assertEqual(len(self.conversation), len(self.conversation.items()))

        new_items = {}
        for a, b in self.conversation.items():
            new_items[a] = b
        self.assertEqual(self.conversation.__dict__, new_items)

    def test_keys(self):
        self.assertIsInstance(self.conversation.keys(), type({}.keys()))
        self.assertEqual(len(self.conversation), len(self.conversation.keys()))

    def test_values(self):
        self.assertIsInstance(self.conversation.values(), type({}.values()))
        self.assertEqual(len(self.conversation), len(self.conversation.values()))

    def test_get(self):
        self.assertIsNone(self.conversation.get("random"))
        self.assertEqual(self.conversation.get("script_meta"), self.script_meta)

    def test_to_json(self):
        self.assertIsInstance(self.conversation.to_json(), dict)

    def test_reset_values(self):
        self.conversation.user_language = 'foo'
        self.conversation.reset_values()
        self.assertIsNone(self.conversation["user_language"])
        self.assertEqual(self.conversation["script_meta"], self.script_meta)


class TestConversationManager(unittest.TestCase):

    def setUp(self) -> None:
        self.script_meta = {"foo": "bar"}
        self.script_filename = "foo"
        self.conversation = Conversation(script_meta=self.script_meta, script_filename=self.script_filename)
        self.manager = ConversationManager()

    def test_len(self):
        self.assertIsInstance(len(self.manager), int)
        self.assertEqual(len(self.manager), len(self.manager._conversation_stack))

    def test_conversation_stack_property(self):
        self.assertIsInstance(self.manager.conversation_stack, list)
        self.assertIs(self.manager.conversation_stack, self.manager._conversation_stack)
        with self.assertRaises(AttributeError):
            self.manager.conversation_stack = ["foo", "bar"]

    def test_user_property(self):
        self.assertIsNone(self.manager.user)
        self.assertIs(self.manager.user, self.manager._user)

        self.manager._user = "foo"
        self.assertEqual(self.manager.user, "foo")
        with self.assertRaises(AttributeError):
            self.manager.user = "bar"

    def test_push(self):
        stack_length = len(self.manager)
        self.manager.push(self.conversation)
        self.assertEqual(stack_length+1, len(self.manager))

        with self.assertRaises(TypeError):
            self.manager.push("foo")

    def test_pop(self):
        self.manager._conversation_stack = ["foo"]
        stack_length = len(self.manager)
        with self.assertRaises(ValueError):
            self.manager.pop()
        self.assertEqual(len(self.manager), stack_length-1)

        self.manager._conversation_stack = [self.conversation]
        self.assertIsInstance(self.manager.pop(), Conversation)
        self.assertIsNone(self.manager.pop())

    def test_get_current_conversation(self):
        self.assertIsNone(self.manager.get_current_conversation())

        self.manager.push(self.conversation)
        self.assertIs(self.manager.get_current_conversation(), self.conversation)

        self.manager._conversation_stack = ["foo", "bar"]
        with self.assertRaises(TypeError):
            self.manager.get_current_conversation()

    def test_update_user_scope(self):
        self.conversation._script_filename = "test"
        self.conversation.variables = {"foo": "bar"}
        self.manager.update_user_scope(self.conversation)
        self.assertEqual(len(self.manager.user_scope_variables), len(self.conversation.variables))

    def test_lookup_user_scope(self):
        self.manager.user_scope_variables = {"foo.bar": "foobar"}
        self.assertEqual(self.manager.lookup_user_scope("foo.bar"), "foobar")
        self.assertIsNone(self.manager.lookup_user_scope("foo.bar.baz"))

    def test_lookup_variable_in_conversation(self):
        self.conversation._script_filename = "foobar"
        self.conversation.variables = {"foo": "bar"}
        self.manager._conversation_stack.append(self.conversation)
        self.assertEqual(self.manager.lookup_variable_in_conversation("foobar.foo"), "bar")
        self.assertIsNone(self.manager.lookup_variable_in_conversation("foobar.foo.baz"))
        self.assertIsNone(self.manager.lookup_variable_in_conversation("foobar."))
        self.assertIsNone(self.manager.lookup_variable_in_conversation(".foo"))
        self.assertIsNone(self.manager.lookup_variable_in_conversation("."))
        self.assertIsNone(self.manager.lookup_variable_in_conversation(""))


if __name__ == '__main__':
    unittest.main()
