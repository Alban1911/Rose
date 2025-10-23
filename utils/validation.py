#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Input validation utilities
Provides decorators and functions for validating inputs
"""

# Standard library imports
from functools import wraps
from typing import Any, Callable


def validate_skin_id(skin_id: Any) -> None:
    """
    Validate that skin_id is a valid integer
    
    Args:
        skin_id: Value to validate
        
    Raises:
        TypeError: If skin_id is not an integer
        ValueError: If skin_id is negative
    """
    if not isinstance(skin_id, int):
        raise TypeError(f"skin_id must be an integer, got {type(skin_id).__name__}")
    if skin_id < 0:
        raise ValueError(f"skin_id must be non-negative, got {skin_id}")


def validate_skin_name(skin_name: Any) -> None:
    """
    Validate that skin_name is a valid non-empty string
    
    Args:
        skin_name: Value to validate
        
    Raises:
        TypeError: If skin_name is not a string
        ValueError: If skin_name is empty or whitespace
    """
    if not isinstance(skin_name, str):
        raise TypeError(f"skin_name must be a string, got {type(skin_name).__name__}")
    if not skin_name or not skin_name.strip():
        raise ValueError("skin_name cannot be empty or whitespace")


def validate_champion_id(champ_id: Any) -> None:
    """
    Validate that champion_id is a valid integer
    
    Args:
        champ_id: Value to validate
        
    Raises:
        TypeError: If champ_id is not an integer
        ValueError: If champ_id is not positive
    """
    if not isinstance(champ_id, int):
        raise TypeError(f"champion_id must be an integer, got {type(champ_id).__name__}")
    if champ_id <= 0:
        raise ValueError(f"champion_id must be positive, got {champ_id}")


def validate_positive_number(value: Any, name: str = "value") -> None:
    """
    Validate that a value is a positive number
    
    Args:
        value: Value to validate
        name: Name of the parameter for error messages
        
    Raises:
        TypeError: If value is not a number
        ValueError: If value is not positive
    """
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def require_non_empty_list(value: Any, name: str = "list") -> None:
    """
    Validate that a value is a non-empty list
    
    Args:
        value: Value to validate
        name: Name of the parameter for error messages
        
    Raises:
        TypeError: If value is not a list
        ValueError: If list is empty
    """
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{name} cannot be empty")


def validated_method(func: Callable) -> Callable:
    """
    Decorator to add validation to methods
    Add validation logic in the decorated function
    
    Example:
        @validated_method
        def show_button(self, skin_id: int, skin_name: str):
            validate_skin_id(skin_id)
            validate_skin_name(skin_name)
            # ... rest of method
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

