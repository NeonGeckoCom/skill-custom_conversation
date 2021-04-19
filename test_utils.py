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
    global conversation
    conversation = Conversation()

    def test_getitem(self):
        self.assertEqual(conversation["script_meta"], conversation.script_meta)

    def test_setitem(self):
        conversation["line"] = "random"
        self.assertEqual(conversation.line, "random")

    def test_contains(self):
        self.assertTrue("script_meta" in conversation)
        self.assertFalse("random" in conversation)

    def test_len(self):
        conversation_length = len(conversation)
        self.assertEqual(type(conversation_length), int)
        conversation.foo = "bar"
        self.assertEqual(len(conversation), conversation_length+1)

    def test_setitem_protected(self):
        with self.assertRaises(AttributeError):
            conversation["_protected"] = "random"

    def test_setitem_protected_with_for_items_loop(self):
        with self.assertRaises(AttributeError):
            for a, b in conversation.items():
                if a.startswith("_"):
                    conversation[a] = "new_value"

    def test_protected_property(self):
        self.assertEqual(conversation["protected"], "protected")

        conversation._protected = "random"
        self.assertEqual(conversation["_protected"], "random")
        with self.assertRaises(AttributeError):
            conversation["protected"] = "protected"

    def test_items(self):
        self.assertEqual(type(conversation.items()), type({}.items()))
        self.assertEqual(len(conversation), len(conversation.items()))

        new_items = {}
        for a, b in conversation.items():
            new_items[a] = b
        self.assertEqual(conversation.__dict__, new_items)

    def test_keys(self):
        self.assertEqual(type(conversation.keys()), type({}.keys()))
        self.assertEqual(len(conversation), len(conversation.keys()))

    def test_values(self):
        self.assertEqual(type(conversation.values()), type({}.values()))
        self.assertEqual(len(conversation), len(conversation.values()))

    def test_get(self):
        self.assertEqual(conversation.get("random"), None)
        self.assertEqual(conversation.get("script_meta"), {})

    def test_to_json(self):
        self.assertEqual(type(conversation.to_json()), dict)


class TestConversationManager(unittest.TestCase):
    global manager
    manager = ConversationManager()

    def test_len(self):
        self.assertEqual(type(len(manager)), int)
        self.assertEqual(len(manager), len(manager._conversation_stack))

    def test_conversation_stack_property(self):
        self.assertEqual(type(manager.conversation_stack), list)
        self.assertIs(manager.conversation_stack, manager._conversation_stack)
        with self.assertRaises(AttributeError):
            manager.conversation_stack = ["foo", "bar"]

    def test_user_property(self):
        self.assertEqual(type(manager.user), type(None))
        self.assertIs(manager.user, manager._user)

        manager._user = "foo"
        self.assertEqual(manager.user, "foo")
        with self.assertRaises(AttributeError):
            manager.user = "bar"

    def test_push(self):
        test_conversation = Conversation()
        stack_length = len(manager)
        manager.push(test_conversation)
        self.assertEqual(stack_length+1, len(manager))

        with self.assertRaises(TypeError):
            manager.push("foo")

    def test_pop(self):
        manager._conversation_stack = ["foo"]
        stack_length = len(manager)
        manager.pop()
        self.assertEqual(len(manager), stack_length-1)

        manager._conversation_stack = []
        self.assertEqual(manager.pop(), None)

    def test_get_current_conversation(self):
        self.assertEqual(manager.get_current_conversation(), None)

        test_conversation = Conversation()
        manager.push(test_conversation)
        self.assertIs(manager.get_current_conversation(), test_conversation)

        manager._conversation_stack = ["foo", "bar"]
        with self.assertRaises(TypeError):
            manager.get_current_conversation()

    def test_update_user_scope(self):
        test_conversation = Conversation()
        test_conversation.script_filename = "test"
        test_conversation.variables = {"foo": "bar"}
        manager.update_user_scope(test_conversation)
        self.assertEqual(len(manager.user_scope_variables), len(test_conversation.variables))

    def test_lookup_user_scope(self):
        lookup_manager = ConversationManager()
        lookup_manager.user_scope_variables = {"foo.bar": "foobar"}
        self.assertEqual(lookup_manager.lookup_user_scope("foo.bar"), "foobar")
        self.assertEqual(lookup_manager.lookup_user_scope("foo.bar.baz"), None)

    def test_lookup_variable_in_conversation(self):
        test_conversation = Conversation()
        test_conversation.script_filename = "foobar"
        test_conversation.variables = {"foo": "bar"}
        test_manager = ConversationManager()
        test_manager._conversation_stack.append(test_conversation)
        self.assertEqual(test_manager.lookup_variable_in_conversation("foobar.foo"), "bar")
        self.assertEqual(test_manager.lookup_variable_in_conversation("foobar.foo.baz"), None)
        self.assertEqual(test_manager.lookup_variable_in_conversation("foobar."), None)
        self.assertEqual(test_manager.lookup_variable_in_conversation(".foo"), None)
        self.assertEqual(test_manager.lookup_variable_in_conversation("."), None)
        self.assertEqual(test_manager.lookup_variable_in_conversation(""), None)


if __name__ == '__main__':
    unittest.main()
