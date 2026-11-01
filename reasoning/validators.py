def _skip_group(latex: str, index: int) -> int:
    depth = 0
    while index < len(latex):
        char = latex[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _count_following_atoms(latex: str, index: int) -> int:
    count = 0
    while index < len(latex) and count < 2:
        while index < len(latex) and latex[index].isspace():
            index += 1
        if index >= len(latex) or latex[index] in "})]":
            break

        char = latex[index]
        if char == "{":
            index = _skip_group(latex, index)
        elif char == "\\":
            index += 1
            if index < len(latex) and latex[index].isalpha():
                while index < len(latex) and latex[index].isalpha():
                    index += 1
            elif index < len(latex):
                index += 1
        else:
            index += 1
        count += 1
    return count


def _read_environment(latex: str, index: int) -> tuple[str | None, int]:
    original_index = index
    while index < len(latex) and latex[index].isspace():
        index += 1
    if index >= len(latex) or latex[index] != "{":
        return None, original_index

    end = index + 1
    while end < len(latex) and latex[end] != "}":
        if latex[end] == "\\":
            end += 2
        else:
            end += 1
    if end >= len(latex):
        return None, original_index

    environment = latex[index + 1:end].strip()
    if not environment:
        return None, original_index
    return environment, end + 1


def _skip_command(latex: str, index: int) -> int:
    index += 1
    if index < len(latex) and latex[index].isalpha():
        while index < len(latex) and latex[index].isalpha():
            index += 1
    elif index < len(latex):
        index += 1
    return index


def _has_duplicate_scripts(latex: str) -> bool:
    seen_scripts = set()
    index = 0

    while index < len(latex):
        char = latex[index]
        if char.isspace():
            index += 1
            continue

        if char in "^_":
            if char in seen_scripts:
                return True
            seen_scripts.add(char)
            index += 1
            while index < len(latex) and latex[index].isspace():
                index += 1
            if index >= len(latex):
                return False
            if latex[index] == "{":
                group_end = _skip_group(latex, index)
                group_content_end = (
                    group_end - 1 if latex[group_end - 1] == "}" else group_end
                )
                if _has_duplicate_scripts(latex[index + 1:group_content_end]):
                    return True
                index = group_end
            elif latex[index] == "\\":
                index = _skip_command(latex, index)
            else:
                index += 1
            continue

        seen_scripts.clear()
        if char == "{":
            group_end = _skip_group(latex, index)
            group_content_end = (
                group_end - 1 if latex[group_end - 1] == "}" else group_end
            )
            if _has_duplicate_scripts(latex[index + 1:group_content_end]):
                return True
            index = group_end
        elif char == "\\":
            index = _skip_command(latex, index)
        else:
            index += 1

    return False


def validate_structure(latex: str) -> list[str]:
    if not isinstance(latex, str):
        raise TypeError("latex must be a string")
    if not latex.strip():
        return ["empty_latex"]

    opening_to_closing = {"(": ")", "[": "]", "{": "}"}
    closing_brackets = set(opening_to_closing.values())
    bracket_stack = []
    left_right_stack = []
    environment_stack = []
    bracket_error = False
    left_right_error = False
    environment_error = False
    frac_error = False
    script_error = False
    index = 0

    while index < len(latex):
        char = latex[index]

        if char == "\\":
            index += 1
            if index >= len(latex):
                break
            if latex[index] == "\\":
                index += 1
                continue
            if latex[index].isalpha():
                command_start = index
                while index < len(latex) and latex[index].isalpha():
                    index += 1
                command = latex[command_start:index]
                if command == "left":
                    left_right_stack.append(command)
                elif command == "right":
                    if left_right_stack:
                        left_right_stack.pop()
                    else:
                        left_right_error = True
                elif command in {"begin", "end"}:
                    environment, environment_end = _read_environment(latex, index)
                    if environment is None:
                        environment_error = True
                    else:
                        if command == "begin":
                            environment_stack.append(environment)
                        elif environment_stack and environment_stack[-1] == environment:
                            environment_stack.pop()
                        else:
                            environment_error = True
                        index = environment_end
                elif command == "frac":
                    if _count_following_atoms(latex, index) < 2:
                        frac_error = True
                continue
            index += 1
            continue

        if char in opening_to_closing:
            bracket_stack.append(opening_to_closing[char])
        elif char in closing_brackets:
            if not bracket_stack or bracket_stack.pop() != char:
                bracket_error = True
        elif char in "^_":
            previous_index = index - 1
            next_index = index + 1
            while previous_index >= 0 and latex[previous_index].isspace():
                previous_index -= 1
            while next_index < len(latex) and latex[next_index].isspace():
                next_index += 1
            if (
                previous_index < 0
                or next_index >= len(latex)
                or latex[previous_index] in "{([=+-*/^_"
                or latex[next_index] in "})]^_"
            ):
                script_error = True

        index += 1

    issues = []
    if bracket_error or bracket_stack:
        issues.append("unbalanced_brackets")
    if left_right_error or left_right_stack:
        issues.append("unbalanced_left_right")
    if environment_error or environment_stack:
        issues.append("unbalanced_environments")
    if frac_error:
        issues.append("invalid_frac")
    if script_error or _has_duplicate_scripts(latex):
        issues.append("invalid_scripts")
    return issues
