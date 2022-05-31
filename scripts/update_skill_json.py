# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import json
from os.path import dirname, join
from pprint import pprint
from neon_utils.packaging_utils import build_skill_spec

skill_dir = dirname(dirname(__file__))


def get_skill_json():
    print(f"skill_dir={skill_dir}")
    skill_json = join(skill_dir, "skill.json")
    skill_spec = build_skill_spec(skill_dir)
    # TODO: patching extra info, consider restructure of readme and/or parser
    #   code blocks should be ignored in parsing
    skill_spec.pop("how to use")
    skill_spec.pop("what are scripts?")
    skill_spec.pop("script syntax")
    skill_spec.pop("how to use scripts")
    skill_spec.pop("starting a script file")
    skill_spec.pop("code here will be executed after 10 seconds of inactivity")
    skill_spec.pop("removed speak to troubleshoot voice_input")
    skill_spec.pop("script continues here")
    skill_spec.pop("script keywords and spacing")
    pprint(skill_spec)
    try:
        with open(skill_json) as f:
            current = json.load(f)
    except Exception as e:
        print(e)
        current = None
    if current != skill_spec:
        print("Skill Updated. Writing skill.json")
        with open(skill_json, 'w+') as f:
            json.dump(skill_spec, f, indent=4)
    else:
        print("No changes to skill.json")


if __name__ == "__main__":
    get_skill_json()
